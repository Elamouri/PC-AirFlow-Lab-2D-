"""2D airflow + heat solver for a PC case (side view, averaged across the case width).

Incompressible Navier-Stokes with Boussinesq buoyancy on a staggered (MAC) grid, MacCormack
advection, an exact pressure projection (sparse LU, factorised once per layout), fans as
momentum sources following blade-element fan curves, heat sinks as porous blocks that pass
their power to the air through a lumped heat-sink temperature.  Real units: m, s, Pa, W.
"""
import time
import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from .layout import FLUID, SOLID, AMB, CFM
from .thermal import fan_curve_frac, curve_temp

CP = 1005.0
GBETA = 9.81 / 295.0
NU = 5.0e-4            # effective (turbulent) viscosity, m^2/s
ALPHA = 5.5e-4         # effective thermal diffusivity, m^2/s
AUTO_EVERY = 0.30      # s between auto-fan speed updates (like a fan header's sampling)
AUTO_STEP = 0.10       # largest speed change per update (0..1)


def bilerp(f, X, Y, minmax=False):
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


class Solver:
    def __init__(self, layout, n_particles=1200, seed=1, dt=None, previous=None):
        L = self.L = layout
        self.NX, self.NY, self.h = L.NX, L.NY, L.h
        NX, NY, h = self.NX, self.NY, self.h
        self.dt = dt if dt else 0.7 * h / 1.0
        self.t = 0.0
        self.room = L.room
        self.rho = L.rho                         # thinner air at altitude carries less heat
        self.rhocp = self.rho * CP
        self.rng = np.random.default_rng(seed)
        ct = L.ct
        ns = ct != SOLID
        amb = ct == AMB
        self.solid = ~ns
        self.nsf = ns.astype(float)
        self.fl = ct == FLUID
        self.flf = self.fl.astype(float)
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
        self.umf, self.vmf = um.astype(float), vm.astype(float)
        self.amb_left = np.nonzero(amb[:, 0])[0]
        self.amb_right = np.nonzero(amb[:, NX - 1])[0]
        self.amb_top = np.nonzero(amb[NY - 1, :])[0]
        self.amb_bot = np.nonzero(amb[0, :])[0]

        Ku = np.zeros((NY, NX + 1))
        Ku[:, 1:NX] = 0.5 * (L.Kx[:, :-1] + L.Kx[:, 1:])
        Kv = np.zeros((NY + 1, NX))
        Kv[1:NY, :] = 0.5 * (L.Ky[:-1, :] + L.Ky[1:, :])
        self.du = 1.0 / (1.0 + self.dt * Ku)
        self.dv = 1.0 / (1.0 + self.dt * Kv)

        # heat sources (lumped heat-sink temperature per part)
        self.hs = []
        for src in L.heat:
            hdt = self.dt * src['H']
            self.hs.append(dict(name=src['name'], idx=src['idx'], a=hdt / (1 + hdt), P=src['P'],
                                Ts=self.room + 8.0, q=0.0, C=1.5))

        # pressure Poisson matrix (it depends only on which cells are air: same walls and parts = same matrix,
        # so a change of fan speed, load or temperature keeps the factorisation and the edit applies at once)
        nfl = int(self.fl.sum())
        same = (previous is not None and getattr(previous, 'lu', None) is not None
                and previous.L.ct.shape == ct.shape and np.array_equal(previous.L.ct, ct))
        idx = -np.ones((NY, NX), np.int64)
        idx[self.fl] = np.arange(nfl)
        jj, ii = np.nonzero(self.fl)
        diag = np.zeros(nfl)
        rows, cols = [], []
        for dj, di in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nj, ni = jj + dj, ii + di
            nbt = ct[nj, ni]
            diag -= (nbt != SOLID)
            m = nbt == FLUID
            rows.append(idx[jj[m], ii[m]])
            cols.append(idx[nj[m], ni[m]])
        rows = np.concatenate(rows)
        cols = np.concatenate(cols)
        t0 = time.time()
        if same:
            self.lu = previous.lu
        else:
            A = sp.coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(nfl, nfl)) + sp.diags(diag)
            self.lu = spla.splu(A.tocsc(), permc_spec='MMD_AT_PLUS_A')
        self.t_factor = time.time() - t0
        self.phi = np.zeros((NY, NX))
        self.p_ema = np.zeros((NY, NX))
        self.src = np.zeros((NY, NX))

        # state
        self.u = np.zeros((NY, NX + 1))
        self.v = np.zeros((NY + 1, NX))
        self.T = np.full((NY, NX), self.room)
        if previous is not None and previous.u.shape == self.u.shape:
            self.u = previous.u * self.umf
            self.v = previous.v * self.vmf
            self.T = previous.T.copy()
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
        self.Ju, self.Iu = [a.astype(float) for a in np.mgrid[0:NY, 0:NX + 1]]
        self.Jv, self.Iv = [a.astype(float) for a in np.mgrid[0:NY + 1, 0:NX]]
        self.Jc, self.Ic = [a.astype(float) for a in np.mgrid[0:NY, 0:NX]]
        self.ramp_t0 = self.t if previous is None else -1.0

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

    # ------------------------------------------------------------------ helpers
    def adv(self, f, U, V, I, J):
        s = self.dt / self.h
        dI = s * U
        dJ = s * V
        fh, lo, hi = bilerp(f, I - dI, J - dJ, minmax=True)
        ft = bilerp(fh, I + dI, J + dJ)
        return np.minimum(np.maximum(fh + 0.5 * (f - ft), lo), hi)

    def extrap_T(self):
        T, ns = self.T, self.nsf
        Tm = T * ns
        s = np.zeros_like(T)
        n = np.zeros_like(T)
        s[:, 1:] += Tm[:, :-1]; n[:, 1:] += ns[:, :-1]
        s[:, :-1] += Tm[:, 1:]; n[:, :-1] += ns[:, 1:]
        s[1:, :] += Tm[:-1, :]; n[1:, :] += ns[:-1, :]
        s[:-1, :] += Tm[1:, :]; n[:-1, :] += ns[1:, :]
        fill = self.solid & (n > 0)
        T[fill] = s[fill] / n[fill]

    # ------------------------------------------------------------------ one time step
    def step(self):
        dt, h, NX, NY = self.dt, self.h, self.NX, self.NY
        u, v, T = self.u, self.v, self.T
        u1 = self.adv(u, u, v_at_u(v), self.Iu, self.Ju)
        v1 = self.adv(v, u_at_v(u), v, self.Iv, self.Jv)
        self.extrap_T()
        T1 = self.adv(T, 0.5 * (u[:, :-1] + u[:, 1:]), 0.5 * (v[:-1, :] + v[1:, :]), self.Ic, self.Jc)

        v1[1:NY, :] += dt * GBETA * (0.5 * (T1[:-1, :] + T1[1:, :]) - self.room) * self.vmf[1:NY, :]

        ramp = 1.0 if self.ramp_t0 < 0 else min(1.0, (self.t - self.ramp_t0) / 0.3)
        uf, vf = u1.reshape(-1), v1.reshape(-1)
        for f in self.L.fans:
            if not f.active:
                continue
            arr = uf if f.axis == 'x' else vf
            q_row = f.sign * arr[f.F].mean(axis=1)
            dp = np.clip(f.pmax * (f.w - q_row / f.ufree), -f.pmax, 2.0 * f.pmax) * ramp
            arr[f.F] += (dt * f.sign / (self.rho * f.n_ax * h)) * dp[:, None]
            f.q = float(q_row.mean())

        c = 0.5 * dt * NU / (h * h)
        for _ in range(2):
            lap = np.zeros_like(u1)
            lap[1:-1, 1:-1] = u1[1:-1, 2:] + u1[1:-1, :-2] + u1[2:, 1:-1] + u1[:-2, 1:-1] - 4 * u1[1:-1, 1:-1]
            u1 += c * lap * self.umf
            lap = np.zeros_like(v1)
            lap[1:-1, 1:-1] = v1[1:-1, 2:] + v1[1:-1, :-2] + v1[2:, 1:-1] + v1[:-2, 1:-1] - 4 * v1[1:-1, 1:-1]
            v1 += c * lap * self.vmf
        u1 *= self.du
        v1 *= self.dv
        u1 *= self.umf
        v1 *= self.vmf

        # side-panel fans: volume sources / sinks following their fan curve
        src = self.src
        src[:] = 0.0
        p_now = self.p_ema
        for sd in self.L.sides:
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

        div = (u1[:, 1:] - u1[:, :-1] + v1[1:, :] - v1[:-1, :])
        rhs = h * div[self.fl] - h * h * src[self.fl]
        phi = self.phi
        phi[self.fl] = self.lu.solve(rhs)
        u1[:, 1:NX] -= self.umf[:, 1:NX] * (phi[:, 1:] - phi[:, :-1]) / h
        v1[1:NY, :] -= self.vmf[1:NY, :] * (phi[1:, :] - phi[:-1, :]) / h
        u1[self.amb_left, 0] = u1[self.amb_left, 1]
        u1[self.amb_right, NX] = u1[self.amb_right, NX - 1]
        v1[NY, self.amb_top] = v1[NY - 1, self.amb_top]
        v1[0, self.amb_bot] = v1[1, self.amb_bot]
        self.p_ema += min(1.0, dt / 0.05) * (self.rho * phi / dt - self.p_ema)

        # temperature: diffusion, fresh air from side intakes, heat sinks
        ca = 0.5 * dt * ALPHA / (h * h)
        for _ in range(2):
            lapT = np.zeros_like(T1)
            fx = (T1[:, 1:] - T1[:, :-1]) * self.umf[:, 1:NX]
            lapT[:, :-1] += fx
            lapT[:, 1:] -= fx
            fy = (T1[1:, :] - T1[:-1, :]) * self.vmf[1:NY, :]
            lapT[:-1, :] += fy
            lapT[1:, :] -= fy
            T1 += ca * lapT * self.flf
        pos = src > 0
        if pos.any():
            T1[pos] = (T1[pos] + dt * src[pos] * self.room) / (1 + dt * src[pos])
        Tf = T1.reshape(-1)
        for hsrc in self.hs:
            idx = hsrc['idx']
            if len(idx) == 0:
                continue
            Told = Tf[idx]
            dTa = hsrc['a'] * (hsrc['Ts'] - Told)
            Tf[idx] = Told + dTa
            q = dTa.sum() * self.rhocp * h * h * self.L.W / dt
            hsrc['q'] = q
            hsrc['Ts'] += dt * (hsrc['P'] - q) / hsrc['C']

        rL, rR, cT, cB = self.amb_left, self.amb_right, self.amb_top, self.amb_bot
        room = self.room
        T1[rR, NX - 1] = np.where(u1[rR, NX - 1] < 0, room, T1[rR, NX - 2])
        T1[NY - 1, cT] = np.where(v1[NY - 1, cT] < 0, room, T1[NY - 2, cT])
        T1[rL, 0] = np.where(u1[rL, 1] > 0, room, T1[rL, 1])
        T1[0, cB] = np.where(v1[1, cB] > 0, room, T1[1, cB])

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
            vel = op['out_sign'] * arr[op['faces']]
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
        box = self.fl & (self.L.Kx == 0) & (self.L.Ky == 0)
        r['p_case'] = float(self.p_ema[box].mean())
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
