"""2D airflow + heat solver for a PC case (side view, averaged across the case width).

Incompressible Navier-Stokes with Boussinesq buoyancy on a staggered (MAC) grid, MacCormack
advection, an exact pressure projection (sparse LU, factorised once per layout), fans as
momentum sources following blade-element fan curves, heat sinks as porous blocks that pass
their power to the air through a lumped heat-sink temperature.  Real units: m, s, Pa, W.

Speed: a step makes no new arrays.  Every work array is made once with the solver, the flow and
temperature fields are float32, all fans and all heat sinks are handled at once, and what only
depends on the walls and parts (pressure factorisation, index lists) is shared with the next
solver when they stay the same.
"""
import time

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from scipy.sparse.csgraph import connected_components

from .layout import FLUID, SOLID, AMB, CFM
from .thermal import fan_curve_frac, curve_temp

CP = 1005.0
GBETA = 9.81 / 295.0
NU = 5.0e-4            # effective (turbulent) viscosity, m^2/s
ALPHA = 5.5e-4         # effective thermal diffusivity, m^2/s
AUTO_EVERY = 0.30      # s between auto-fan speed updates (like a fan header's sampling)
AUTO_STEP = 0.10       # largest speed change per update (0..1)
REF_STEP = 0.7         # time step: 0.7 x cell / (1 m/s), the step the porous resistances were tuned with
LIVE_STEP = 1.0        # the live view's longer step: the air moves 1.4x further per step, and the resistances
                       # keep their tuned loss per second (Solver.damping); results stay within ~0.5 K / 2 %
REAL = np.float32      # flow and temperature fields


def bilerp(f, X, Y, minmax=False):
    """bilinear value of f at grid positions (X, Y) (the plain version, used for the flow dashes)"""
    ny, nx = f.shape
    X = np.clip(X, 0.0, nx - 1.0001)
    Y = np.clip(Y, 0.0, ny - 1.0001)
    i0 = X.astype(np.int64)
    j0 = Y.astype(np.int64)
    fx = X - i0
    fy = Y - j0
    k = j0 * nx + i0
    ff = f.ravel()
    a = ff.take(k)
    b = ff.take(k + 1)
    c = ff.take(k + nx)
    d = ff.take(k + nx + 1)
    val = (a + (b - a) * fx) * (1 - fy) + (c + (d - c) * fx) * fy
    if minmax:
        return val, np.minimum(np.minimum(a, b), np.minimum(c, d)), np.maximum(np.maximum(a, b), np.maximum(c, d))
    return val


def v_at_u(v):
    vp = np.pad(v, ((0, 0), (1, 1)), mode='edge')
    return 0.25 * (vp[:-1, :-1] + vp[:-1, 1:] + vp[1:, :-1] + vp[1:, 1:])


def u_at_v(u):
    up = np.pad(u, ((1, 1), (0, 0)), mode='edge')
    return 0.25 * (up[:-1, :-1] + up[:-1, 1:] + up[1:, :-1] + up[1:, 1:])


def advect_reference(f, U, V, s):
    """one MacCormack step done the plain way (the fast Advection below must give the same)"""
    J, I = [a.astype(float) for a in np.mgrid[0:f.shape[0], 0:f.shape[1]]]
    fh, lo, hi = bilerp(f, I - s * U, J - s * V, minmax=True)
    ft = bilerp(fh, I + s * U, J + s * V)
    return np.minimum(np.maximum(fh + 0.5 * (f - ft), lo), hi)


class AdvectionWork:
    """work arrays for advection, shared by u, v and T (they are advected one after the other): a third of
    the memory, so more of it stays in the processor's cache between the pictures"""

    def __init__(self, n, dtype=REAL):
        self.real = [np.empty(n, dtype) for _ in range(11)]
        self.k = np.empty(n, np.intp)


class Advection:
    """MacCormack advection on one grid (u faces, v faces or cells), working in arrays made once"""

    def __init__(self, shape, dtype=REAL, work=None):
        ny, nx = shape
        n = ny * nx
        self.nx = nx
        self.I = np.arange(nx, dtype=dtype)[None, :]             # grid positions (broadcast over the rows ...
        self.J = np.arange(ny, dtype=dtype)[:, None]             # ... and the columns)
        self.xmax, self.ymax = nx - 1.0001, ny - 1.0001
        work = work or AdvectionWork(n, dtype)
        view = lambda a: a[:n].reshape(shape)                    # noqa: E731
        (self.dI, self.dJ, self.X, self.Y, self.a, self.b, self.c, self.d,
         self.lo, self.hi, self.fh) = [view(a) for a in work.real]
        self.k = view(work.k)

    def interp(self, f, X, Y, out, minmax=False):
        """bilinear value of f at (X, Y) into out (X and Y are used as work space);
        with minmax also the smallest / largest of the four values around each point (self.lo / self.hi)"""
        nx, a, b, c, d, k = self.nx, self.a, self.b, self.c, self.d, self.k
        np.clip(X, 0.0, self.xmax, out=X)
        np.clip(Y, 0.0, self.ymax, out=Y)
        np.floor(X, out=a)
        np.floor(Y, out=b)
        X -= a                                                   # fractions
        Y -= b
        b *= nx
        b += a
        np.copyto(k, b, casting='unsafe')                        # cell numbers (whole numbers, exact)
        ff = f.ravel()
        ff.take(k, out=a, mode='clip')
        ff[1:].take(k, out=b, mode='clip')
        ff[nx:].take(k, out=c, mode='clip')
        ff[nx + 1:].take(k, out=d, mode='clip')
        if minmax:
            lo, hi = self.lo, self.hi
            np.minimum(a, b, out=lo)
            np.minimum(lo, c, out=lo)
            np.minimum(lo, d, out=lo)
            np.maximum(a, b, out=hi)
            np.maximum(hi, c, out=hi)
            np.maximum(hi, d, out=hi)
        b -= a                                                   # (a + (b - a) fx) (1 - fy) + (c + (d - c) fx) fy
        b *= X
        b += a
        d -= c
        d *= X
        d += c
        np.subtract(1.0, Y, out=a)
        np.multiply(b, a, out=out)
        d *= Y
        out += d
        return out

    def advect(self, f, U, V, s, out):
        """f carried by the velocity (U, V) (m/s, at f's points) over one step; s = dt / cell size"""
        dI, dJ, X, Y = self.dI, self.dJ, self.X, self.Y
        np.multiply(U, s, out=dI)
        np.multiply(V, s, out=dJ)
        np.subtract(self.I, dI, out=X)
        np.subtract(self.J, dJ, out=Y)
        self.interp(f, X, Y, self.fh, minmax=True)               # back along the flow
        np.add(self.I, dI, out=X)
        np.add(self.J, dJ, out=Y)
        self.interp(self.fh, X, Y, out)                          # and forward again: the error estimate
        np.subtract(f, out, out=out)
        out *= 0.5
        out += self.fh
        np.maximum(out, self.lo, out=out)
        np.minimum(out, self.hi, out=out)
        return out


class Geometry:
    """what only depends on which cells are air: the pressure factorisation and index lists.
    Same walls and parts = same Geometry, so a change of fan speed, load or temperature keeps it."""

    def __init__(self, ct):
        self.ct = ct.copy()
        NY, NX = ct.shape
        fl = ct == FLUID
        ns = ct != SOLID
        self.fl_idx = np.flatnonzero(fl)
        nfl = len(self.fl_idx)
        idx = -np.ones((NY, NX), np.int64)
        idx[fl] = np.arange(nfl)
        jj, ii = np.nonzero(fl)
        diag = np.zeros(nfl)
        to_room = np.zeros(nfl, bool)                            # next to an opening
        rows, cols = [], []
        for dj, di in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nj, ni = jj + dj, ii + di
            nbt = ct[nj, ni]
            diag -= (nbt != SOLID)
            to_room |= nbt == AMB
            m = nbt == FLUID
            rows.append(idx[jj[m], ii[m]])
            cols.append(idx[nj[m], ni[m]])
        rows = np.concatenate(rows)
        cols = np.concatenate(cols)
        # air with no way out (a case without fans, a pocket closed in by blocks) has no pressure of its own and
        # makes the matrix singular: one cell of each such pocket is tied to the room, like a small gap
        links = sp.coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(nfl, nfl))
        n_comp, comp = connected_components(links, directed=False)
        opened = np.zeros(n_comp, bool)
        opened[comp[to_room]] = True
        shut = np.flatnonzero(~opened)
        self.sealed = []                                         # cells of air in each closed pocket
        if len(shut):
            order = np.argsort(comp, kind='stable')
            diag[order[np.searchsorted(comp[order], shut)]] -= 1.0
            self.sealed = [int(n) for n in np.bincount(comp, minlength=n_comp)[shut]]
        self.n_air = nfl
        t0 = time.time()
        A = links + sp.diags(diag)
        self.lu = spla.splu(A.tocsc(), permc_spec='MMD_AT_PLUS_A')
        self.t_factor = time.time() - t0
        # solid cells next to air get the mean temperature of their air neighbours (smooth advection at walls)
        jj, ii = np.nonzero(~ns)
        src, dst = [], []
        count = np.zeros(len(jj))
        for dj, di in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            nj, ni = jj + dj, ii + di
            ok = (nj >= 0) & (nj < NY) & (ni >= 0) & (ni < NX)
            ok[ok] = ns[nj[ok], ni[ok]]
            count += ok
            dst.append(np.flatnonzero(ok))
            src.append(nj[ok] * NX + ni[ok])
        dst = np.concatenate(dst)
        src = np.concatenate(src)
        keep = count > 0
        order = -np.ones(len(jj), np.int64)
        order[keep] = np.arange(int(keep.sum()))
        self.fill_idx = (jj * NX + ii)[keep]
        self.fill = sp.csr_matrix(((1.0 / count[dst]).astype(REAL), (order[dst], src)),
                                  shape=(len(self.fill_idx), NY * NX))

    def same(self, ct):
        return self.ct.shape == ct.shape and np.array_equal(self.ct, ct)


class Solver:
    def __init__(self, layout, n_particles=1200, seed=1, dt=None, previous=None):
        L = self.L = layout
        self.NX, self.NY, self.h = L.NX, L.NY, L.h
        NX, NY, h = self.NX, self.NY, self.h
        self.dt = dt if dt else REF_STEP * h / 1.0
        self.t = 0.0
        self.room = float(L.room)
        self.rho = L.rho                         # thinner air at altitude carries less heat
        self.rhocp = self.rho * CP
        self.rng = np.random.default_rng(seed)
        ct = L.ct
        ns = ct != SOLID
        amb = ct == AMB
        self.solid = ~ns
        self.nsf = ns.astype(REAL)
        self.fl = ct == FLUID
        self.flf = self.fl.astype(REAL)
        um = np.zeros((NY, NX + 1), bool)
        um[:, 1:NX] = ns[:, :-1] & ns[:, 1:]
        vm = np.zeros((NY + 1, NX), bool)
        vm[1:NY, :] = ns[:-1, :] & ns[1:, :]
        ut = np.zeros_like(um)
        ut[:, 1:NX] = amb[:, :-1] & amb[:, 1:]
        vt = np.zeros_like(vm)
        vt[1:NY, :] = amb[:-1, :] & amb[1:, :]
        um &= ~ut
        vm &= ~vt
        self.umf, self.vmf = um.astype(REAL), vm.astype(REAL)
        self.amb_left = np.nonzero(amb[:, 0])[0]
        self.amb_right = np.nonzero(amb[:, NX - 1])[0]
        self.amb_top = np.nonzero(amb[NY - 1, :])[0]
        self.amb_bot = np.nonzero(amb[0, :])[0]

        Ku = np.zeros((NY, NX + 1))
        Ku[:, 1:NX] = 0.5 * (L.Kx[:, :-1] + L.Kx[:, 1:])
        Kv = np.zeros((NY + 1, NX))
        Kv[1:NY, :] = 0.5 * (L.Ky[:-1, :] + L.Ky[1:, :])
        self.du = self.damping(Ku).astype(REAL)
        self.dv = self.damping(Kv).astype(REAL)

        # heat sources (lumped heat-sink temperature per part)
        self.hs = []
        for src in L.heat:
            hdt = self.dt * src['H']
            self.hs.append(dict(name=src['name'], idx=src['idx'], a=hdt / (1 + hdt), P=src['P'],
                                Ts=self.room + 8.0, q=0.0, C=1.5))

        # pressure Poisson matrix (it depends only on which cells are air: same walls and parts = same matrix,
        # so a change of fan speed, load or temperature keeps the factorisation and the edit applies at once)
        geo = getattr(previous, 'geo', None)
        t0 = time.time()
        self.geo = geo if (geo is not None and geo.same(ct)) else Geometry(ct)
        self.lu = self.geo.lu
        self.t_factor = time.time() - t0
        sealed = self.geo.sealed
        if sealed:
            if max(sealed) > 0.5 * self.geo.n_air:
                note = ('No fan or opening lets air in or out of the case - the air only moves round inside '
                        '(simulated as if the case had a small gap)')
            else:
                note = ('%d pocket%s of air %s closed in by blocks or parts - that air cannot get out'
                        % (len(sealed), '' if len(sealed) == 1 else 's', 'is' if len(sealed) == 1 else 'are'))
            if note not in L.warnings:
                L.warnings.append(note)
        self.phi = np.zeros((NY, NX))
        self.p_ema = np.zeros((NY, NX))
        self.src = np.zeros((NY, NX))

        # state
        self.u = np.zeros((NY, NX + 1), REAL)
        self.v = np.zeros((NY + 1, NX), REAL)
        self.T = np.full((NY, NX), self.room, REAL)
        if previous is not None and previous.u.shape == self.u.shape:
            self.u[:] = previous.u * self.umf
            self.v[:] = previous.v * self.vmf
            self.T[:] = previous.T
            self.t = previous.t
            old_ts = {b['name']: b['Ts'] for b in previous.hs}
            for a in self.hs:
                if a['name'] in old_ts:
                    a['Ts'] = old_ts[a['name']]
        if previous is not None:                 # auto fans keep the speed they had reached
            old = {f.label: f.frac for f in previous.L.fans if getattr(f, 'auto', False)}
            for f in L.fans:
                if getattr(f, 'auto', False) and f.label in old:
                    L.set_fan_frac(f, old[f.label])
            old_s = {sd['label']: sd['frac'] for sd in previous.L.sides if sd['auto']}
            for sd in L.sides:
                if sd['auto'] and sd['label'] in old_s:
                    L.set_side_frac(sd, old_s[sd['label']])
        self._auto_t = self.t
        self.ramp_t0 = self.t if previous is None else -1.0
        self._prepare()

        # particles for the flow dashes
        fj, fi = np.nonzero(self.fl)
        self.spawn_j, self.spawn_i = fj, fi
        self.NP = n_particles
        self.PX = np.zeros(self.NP)
        self.PY = np.zeros(self.NP)
        self.age = np.zeros(self.NP, int)
        self.life = np.ones(self.NP, int)
        self.respawn(np.ones(self.NP, bool))
        self.age = (self.rng.random(self.NP) * self.life).astype(int)
        self.disp = None
        self.raw = {}
        self.div_res = 0.0

    def damping(self, K):
        """speed kept per step in a porous part (resistance K, 1/s).  The resistances were tuned with
        1 / (1 + dt K) at the reference step; for another step the same loss per second is kept."""
        ref = REF_STEP * self.h
        keep = 1.0 / (1.0 + ref * K)
        if abs(self.dt - ref) < 1e-12 * ref:
            return keep
        return keep ** (self.dt / ref)

    # ------------------------------------------------------------------ work arrays (made once)
    def _prepare(self):
        NX, NY, dt, h = self.NX, self.NY, self.dt, self.h
        work = AdvectionWork(max(NY * (NX + 1), (NY + 1) * NX))
        self._adv = (Advection((NY, NX + 1), work=work), Advection((NY + 1, NX), work=work),
                     Advection((NY, NX), work=work))
        self._spare = (np.zeros((NY, NX + 1), REAL), np.zeros((NY + 1, NX), REAL), np.zeros((NY, NX), REAL))
        self._vu = np.empty((NY, NX + 1), REAL)                  # v at the u faces
        self._uv = np.empty((NY + 1, NX), REAL)                  # u at the v faces
        self._uc = np.empty((NY, NX), REAL)                      # u and v in the cell centres
        self._vc = np.empty((NY, NX), REAL)
        self._buoy = ((dt * GBETA) * self.vmf[1:NY, :]).astype(REAL)
        self._tv = np.empty((NY - 1, NX), REAL)
        c = 0.5 * dt * NU / (h * h)
        self._cu, self._cv = (c * self.umf).astype(REAL), (c * self.vmf).astype(REAL)
        self._lap_u = np.empty((NY - 2, NX - 1), REAL)
        self._lap_v = np.empty((NY - 1, NX - 2), REAL)
        self._four_u = np.empty((NY - 2, NX - 1), REAL)
        self._four_v = np.empty((NY - 1, NX - 2), REAL)
        self._du_m = (self.du * self.umf).astype(REAL)
        self._dv_m = (self.dv * self.vmf).astype(REAL)
        self._div = np.empty((NY, NX), REAL)
        self._rhs = np.empty(len(self.geo.fl_idx))
        self._gx = np.empty((NY, NX - 1))
        self._gy = np.empty((NY - 1, NX))
        self._umf_h = self.umf[:, 1:NX] / h
        self._vmf_h = self.vmf[1:NY, :] / h
        self._pe = np.empty((NY, NX))
        ca = 0.5 * dt * ALPHA / (h * h)
        self._lapT = np.empty((NY, NX), REAL)
        self._fx = np.empty((NY, NX - 1), REAL)
        self._fy = np.empty((NY - 1, NX), REAL)
        self._umf_x = self.umf[:, 1:NX].copy()
        self._vmf_y = self.vmf[1:NY, :].copy()
        self._ca_fl = (ca * self.flf).astype(REAL)
        self._box = self.fl & (self.L.Kx == 0) & (self.L.Ky == 0)
        self._pack_fans()
        self._pack_heat()

    def _pack_fans(self):
        """all fans of one axis in one list of faces, so they are pushed in one go"""
        self._fan_groups = []
        for axis in ('x', 'y'):
            fans = [f for f in self.L.fans if f.axis == axis and f.F.size]
            if not fans:
                continue
            faces = np.concatenate([f.F.ravel() for f in fans])
            if len(np.unique(faces)) != len(faces):              # never seen: fans sharing faces push in turn
                self._fan_groups = None
                return
            n_rows = np.array([f.F.shape[0] for f in fans])
            n_ax = np.array([f.F.shape[1] for f in fans])
            row_fan = np.repeat(np.arange(len(fans)), n_rows)
            row_len = n_ax[row_fan]
            row_start = np.concatenate([[0], np.cumsum(row_len)[:-1]])
            fan_row0 = np.concatenate([[0], np.cumsum(n_rows)[:-1]])
            self._fan_groups.append(dict(axis=axis, fans=fans, faces=faces, row_fan=row_fan, row_len=row_len,
                                         row_start=row_start, fan_row0=fan_row0, n_rows=n_rows,
                                         w=np.concatenate([f.w for f in fans]), vals=np.empty(len(faces), REAL)))

    def _pack_heat(self):
        """all heat sinks in one list of cells (they never share a cell)"""
        live = [hs for hs in self.hs if len(hs['idx'])]
        self._heat = live
        if not live:
            return
        n = np.array([len(hs['idx']) for hs in live])
        self._heat_idx = np.concatenate([hs['idx'] for hs in live])
        self._heat_of = np.repeat(np.arange(len(live)), n)
        self._heat_start = np.concatenate([[0], np.cumsum(n)[:-1]])
        self._heat_a = np.repeat(np.array([hs['a'] for hs in live]), n)
        self._heat_P = np.array([hs['P'] for hs in live])

    # ------------------------------------------------------------------ helpers
    def extrap_T(self):
        """solid cells next to air take the mean temperature of their air neighbours"""
        g = self.geo
        if len(g.fill_idx):
            Tf = self.T.ravel()
            Tf[g.fill_idx] = g.fill @ Tf

    def _v_at_u(self, v):
        out, NX = self._vu, self.NX
        mid = out[:, 1:NX]
        np.add(v[:-1, :-1], v[:-1, 1:], out=mid)
        mid += v[1:, :-1]
        mid += v[1:, 1:]
        for i, k in ((0, 0), (NX, NX - 1)):                     # walls: the edge value counts twice
            out[:, i] = v[:-1, k] + v[:-1, k] + v[1:, k] + v[1:, k]
        out *= 0.25
        return out

    def _u_at_v(self, u):
        out, NY = self._uv, self.NY
        mid = out[1:NY, :]
        np.add(u[:-1, :-1], u[:-1, 1:], out=mid)
        mid += u[1:, :-1]
        mid += u[1:, 1:]
        for j, k in ((0, 0), (NY, NY - 1)):
            out[j, :] = u[k, :-1] + u[k, 1:] + u[k, :-1] + u[k, 1:]
        out *= 0.25
        return out

    @staticmethod
    def _diffuse(x, lap, four, cm):
        """one explicit diffusion sub-step of x (inside the border), cm = coefficient x open faces"""
        mid = x[1:-1, 1:-1]
        np.add(x[1:-1, 2:], x[1:-1, :-2], out=lap)
        lap += x[2:, 1:-1]
        lap += x[:-2, 1:-1]
        np.multiply(mid, 4, out=four)
        lap -= four
        lap *= cm[1:-1, 1:-1]
        mid += lap

    def _push_fans(self, uf, vf, ramp):
        dt, h, rho = self.dt, self.h, self.rho
        if self._fan_groups is None:                            # fans sharing faces: one after the other
            for f in self.L.fans:
                if not f.active:
                    continue
                arr = uf if f.axis == 'x' else vf
                q_row = f.sign * arr[f.F].mean(axis=1)
                dp = np.clip(f.pmax * (f.w - q_row / f.ufree), -f.pmax, 2.0 * f.pmax) * ramp
                arr[f.F] += (dt * f.sign / (rho * f.n_ax * h)) * dp[:, None]
                f.q = float(q_row.mean())
            return
        for g in self._fan_groups:
            fans = g['fans']
            arr = uf if g['axis'] == 'x' else vf
            on = np.array([f.active for f in fans])
            if not on.any():
                continue
            sign = np.array([float(f.sign) for f in fans])
            pmax = np.array([f.pmax if f.active else 0.0 for f in fans])
            ufree = np.array([f.ufree if f.active and f.ufree > 0 else 1.0 for f in fans])
            rf = g['row_fan']
            vals = arr.take(g['faces'], out=g['vals'])
            q_row = np.add.reduceat(vals, g['row_start'], dtype=float)
            q_row *= sign[rf] / g['row_len']
            pm = pmax[rf]
            dp = np.clip(pm * (g['w'] - q_row / ufree[rf]), -pm, 2.0 * pm) * ramp
            dp *= (dt / (rho * h)) * sign[rf] / g['row_len']
            arr[g['faces']] += np.repeat(dp, g['row_len']).astype(REAL)
            q_fan = np.add.reduceat(q_row, g['fan_row0']) / g['n_rows']
            for f, q, a in zip(fans, q_fan, on):
                if a:
                    f.q = float(q)

    def _heat_sinks(self, T1):
        if not self._heat:
            return
        Tf = T1.ravel()
        live = self._heat
        Ts = np.array([hs['Ts'] for hs in live])
        Told = Tf[self._heat_idx]
        dTa = Ts[self._heat_of] - Told
        dTa *= self._heat_a
        Tf[self._heat_idx] = Told + dTa
        q = np.add.reduceat(dTa, self._heat_start) * (self.rhocp * self.h * self.h * self.L.W / self.dt)
        for hs, qq in zip(live, q):
            qq = float(qq)
            hs['q'] = qq
            hs['Ts'] += self.dt * (hs['P'] - qq) / hs['C']

    # ------------------------------------------------------------------ one time step
    def step(self):
        dt, h, NX, NY = self.dt, self.h, self.NX, self.NY
        u, v, T = self.u, self.v, self.T
        u1, v1, T1 = self._spare
        s = dt / h
        adv_u, adv_v, adv_T = self._adv
        adv_u.advect(u, u, self._v_at_u(v), s, u1)
        adv_v.advect(v, self._u_at_v(u), v, s, v1)
        self.extrap_T()
        uc, vc = self._uc, self._vc
        np.add(u[:, :-1], u[:, 1:], out=uc)
        uc *= 0.5
        np.add(v[:-1, :], v[1:, :], out=vc)
        vc *= 0.5
        adv_T.advect(T, uc, vc, s, T1)

        tv = self._tv                                            # buoyancy
        np.add(T1[:-1, :], T1[1:, :], out=tv)
        tv *= 0.5
        tv -= self.room
        tv *= self._buoy
        v1[1:NY, :] += tv

        ramp = 1.0 if self.ramp_t0 < 0 else min(1.0, (self.t - self.ramp_t0) / 0.3)
        self._push_fans(u1.reshape(-1), v1.reshape(-1), ramp)

        for _ in range(2):
            self._diffuse(u1, self._lap_u, self._four_u, self._cu)
            self._diffuse(v1, self._lap_v, self._four_v, self._cv)
        u1 *= self._du_m                                         # porous parts slow the air; walls stop it
        v1 *= self._dv_m

        # side-panel fans: volume sources / sinks following their fan curve
        src = self.src
        sides = self.L.sides
        if sides:
            src[:] = 0.0
            p_now = self.p_ema
            for sd in sides:
                if sd['Qfree'] <= 0:
                    sd['Q'] = 0.0
                    continue
                p_loc = float(p_now.ravel()[sd['idx']].mean())
                sgn = 1.0 if sd['direction'] == 'in' else -1.0
                target = sd['Qfree'] * (1.0 - sgn * p_loc / max(sd['pmax'], 1e-6)) * ramp
                target = float(np.clip(target, 0.0, 1.5 * sd['Qfree']))
                sd['Q'] += min(1.0, dt / 0.05) * (target - sd['Q'])
                per_cell = sgn * sd['Q'] / (len(sd['idx']) * h * h * self.L.W)
                src.ravel()[sd['idx']] += per_cell

        # pressure projection: the air leaving every cell = the air entering it
        div = self._div
        np.subtract(u1[:, 1:], u1[:, :-1], out=div)
        div += v1[1:, :]
        div -= v1[:-1, :]
        fl_idx = self.geo.fl_idx
        rhs = self._rhs
        np.multiply(div.ravel().take(fl_idx), h, out=rhs)
        if sides:
            rhs -= (h * h) * src.ravel().take(fl_idx)
        phi = self.phi
        phi.ravel()[fl_idx] = self.lu.solve(rhs)
        gx, gy = self._gx, self._gy
        np.subtract(phi[:, 1:], phi[:, :-1], out=gx)
        gx *= self._umf_h
        u1[:, 1:NX] -= gx
        np.subtract(phi[1:, :], phi[:-1, :], out=gy)
        gy *= self._vmf_h
        v1[1:NY, :] -= gy
        u1[self.amb_left, 0] = u1[self.amb_left, 1]
        u1[self.amb_right, NX] = u1[self.amb_right, NX - 1]
        v1[NY, self.amb_top] = v1[NY - 1, self.amb_top]
        v1[0, self.amb_bot] = v1[1, self.amb_bot]
        pe = self._pe
        np.multiply(phi, self.rho / dt, out=pe)
        pe -= self.p_ema
        pe *= min(1.0, dt / 0.05)
        self.p_ema += pe

        # temperature: diffusion, fresh air from side intakes, heat sinks
        lapT, fx, fy = self._lapT, self._fx, self._fy
        for _ in range(2):
            np.subtract(T1[:, 1:], T1[:, :-1], out=fx)
            fx *= self._umf_x
            lapT[:, :-1] = fx
            lapT[:, -1] = 0.0
            lapT[:, 1:] -= fx
            np.subtract(T1[1:, :], T1[:-1, :], out=fy)
            fy *= self._vmf_y
            lapT[:-1, :] += fy
            lapT[1:, :] -= fy
            lapT *= self._ca_fl
            T1 += lapT
        if sides:
            pos = src > 0
            if pos.any():
                T1[pos] = (T1[pos] + dt * src[pos] * self.room) / (1 + dt * src[pos])
        self._heat_sinks(T1)

        rL, rR, cT, cB = self.amb_left, self.amb_right, self.amb_top, self.amb_bot
        room = self.room
        T1[rR, NX - 1] = np.where(u1[rR, NX - 1] < 0, room, T1[rR, NX - 2])
        T1[NY - 1, cT] = np.where(v1[NY - 1, cT] < 0, room, T1[NY - 2, cT])
        T1[rL, 0] = np.where(u1[rL, 1] > 0, room, T1[rL, 1])
        T1[0, cB] = np.where(v1[1, cB] > 0, room, T1[1, cB])

        self._spare = (u, v, T)
        self.u, self.v, self.T = u1, v1, T1
        self.t += dt
        self._probe_count = getattr(self, '_probe_count', 0) + 1
        if self._probe_count % 3 == 0:
            self.update_probes()
        if self.L.n_auto and self.t - self._auto_t >= AUTO_EVERY:
            self.update_auto_fans()

    def set_heat_capacity(self, C):
        for hsrc in self.hs:
            hsrc['C'] = C

    def update_auto_fans(self):
        """case fans set to auto follow the fan curve on the current CPU / GPU estimate"""
        self._auto_t = self.t
        if self.disp is None:
            return
        from .results import component_temps          # results imports thermal only
        t_cpu, t_gpu = component_temps(self)
        curve = self.L.cfg.fan_curve
        target = fan_curve_frac(curve, curve_temp(curve, t_cpu, t_gpu))
        if not np.isfinite(target):
            return
        for f in self.L.fans:
            if getattr(f, 'auto', False):
                self.L.set_fan_frac(f, f.frac + float(np.clip(target - f.frac, -AUTO_STEP, AUTO_STEP)))
        for sd in self.L.sides:
            if sd['auto']:
                self.L.set_side_frac(sd, sd['frac'] + float(np.clip(target - sd['frac'], -AUTO_STEP, AUTO_STEP)))

    # ------------------------------------------------------------------ measurements
    def _air_in(self, key):
        pr = self.L.probes.get(key)
        if pr is None or len(pr[1]) == 0:
            return self.room
        arr = self.u if pr[0] == 'u' else self.v
        w = np.maximum(pr[2] * arr.ravel()[pr[1]], 0.0)
        s = w.sum()
        if s < 1e-9:
            return float(self.T.ravel()[pr[3]].mean())
        return float((w * self.T.ravel()[pr[3]]).sum() / s)

    def update_probes(self):
        hD = self.h * self.L.W
        uf, vf, Tf = self.u.ravel(), self.v.ravel(), self.T.ravel()
        r = {'cpu_in': self._air_in('cpu_in'), 'gpu_in': self._air_in('gpu_in')}
        per = {}
        q_in = q_out = heat_out = 0.0
        groups = {}
        for op in self.L.openings:
            arr = uf if op['arr'] == 'u' else vf
            vel = op['out_sign'] * arr[op['faces']].astype(float)
            Qout = float(np.maximum(vel, 0).sum() * hD)
            Qin = float(np.maximum(-vel, 0).sum() * hD)
            w = np.maximum(vel, 0)
            Tout = float((w * Tf[op['tin']]).sum() / w.sum()) if w.sum() > 1e-9 else self.room
            hout = self.rhocp * Qout * (Tout - self.room)
            key = op['owner']
            g = groups.setdefault(key, dict(kind=op['kind'], Qin=0.0, Qout=0.0, heat=0.0, Tw=0.0, wall=op['wall']))
            g['Qin'] += Qin
            g['Qout'] += Qout
            g['heat'] += hout
            g['Tw'] += Tout * Qout
            q_in += Qin
            q_out += Qout
            heat_out += hout
        for sd in self.L.sides:
            Qs = sd['Q']
            Ts_ = float(Tf[sd['idx']].mean())
            g = groups.setdefault(sd['label'], dict(kind='side', Qin=0.0, Qout=0.0, heat=0.0, Tw=0.0, wall='side'))
            if sd['direction'] == 'in':
                g['Qin'] += Qs
                q_in += Qs
            else:
                g['Qout'] += Qs
                g['Tw'] += Ts_ * Qs
                g['heat'] += self.rhocp * Qs * (Ts_ - self.room)
                q_out += Qs
                heat_out += self.rhocp * Qs * (Ts_ - self.room)
        for key, g in groups.items():
            g['T'] = g['Tw'] / g['Qout'] if g['Qout'] > 1e-9 else self.room
            g['CFM_in'] = g['Qin'] * CFM
            g['CFM_out'] = g['Qout'] * CFM
            per[key] = g
        r['p_case'] = float(self.p_ema[self._box].mean()) if self._box.any() else 0.0
        r['cfm_in'] = q_in * CFM
        r['cfm_out'] = q_out * CFM
        r['heat_out'] = heat_out
        r['heat_in'] = sum(hsrc['P'] for hsrc in self.hs)
        for hsrc in self.hs:
            r['Ts_' + hsrc['name']] = hsrc['Ts']
            r['q_' + hsrc['name']] = hsrc['q']
        for f in self.L.fans:
            if f.kind in ('cooler', 'gpu', 'psu'):
                r['CFM_' + f.label] = f.q * (f.span[1] - f.span[0]) * 1e-3 * self.L.W * CFM
        self.raw = r
        self.per = per
        a = min(1.0, 3 * self.dt / 0.25)
        if self.disp is None:
            self.disp = dict(r)
            self.disp_per = {k: dict(v) for k, v in per.items()}
        else:
            for k, val in r.items():
                self.disp[k] = self.disp.get(k, val) + a * (val - self.disp.get(k, val))
            for k, g in per.items():
                d = self.disp_per.setdefault(k, dict(g))
                for kk in ('CFM_in', 'CFM_out', 'T', 'heat'):
                    d[kk] += a * (g[kk] - d[kk])
                d['kind'], d['wall'] = g['kind'], g['wall']

    # ------------------------------------------------------------------ particles
    def respawn(self, mask):
        n = int(mask.sum())
        if n == 0:
            return
        k = self.rng.integers(len(self.spawn_i), size=n)
        self.PX[mask] = self.spawn_i[k] + self.rng.random(n)
        self.PY[mask] = self.spawn_j[k] + self.rng.random(n)
        self.age[mask] = 0
        self.life[mask] = self.rng.integers(45, 110, size=n)

    def move_particles(self, dt=None):
        s = (dt if dt else self.dt) / self.h
        self.PX += s * bilerp(self.u, self.PX, self.PY - 0.5)
        self.PY += s * bilerp(self.v, self.PX - 0.5, self.PY)

    def frame_particles(self):
        i = np.clip(self.PX.astype(int), 0, self.NX - 1)
        j = np.clip(self.PY.astype(int), 0, self.NY - 1)
        self.age += 1
        bad = (self.L.ct[j, i] != FLUID) | (self.age > self.life)
        self.respawn(bad)
        up = bilerp(self.u, self.PX, self.PY - 0.5)
        vp = bilerp(self.v, self.PX - 0.5, self.PY)
        alpha = np.clip(np.minimum(self.age / 8.0, (self.life - self.age) / 8.0), 0, 1)
        h_mm = self.L.h_mm
        return np.stack([(self.PX - 1.0) * h_mm, (self.PY - 1.0) * h_mm, up, vp, alpha], axis=1)

    def interior_T(self):
        return self.T[1:-1, 1:-1]

    def run(self, seconds, callback=None):
        n = int(round(seconds / self.dt))
        for k in range(n):
            self.step()
            if callback and k % 50 == 0:
                callback(k, n)
        self.update_probes()
