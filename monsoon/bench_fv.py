"""Bounded conservative rectangular shallow-water research backend.

This is a separate numerical model, not a correction to SWMM output. Water is
stored in finite-volume channel cells and explicit stage-area compartments.
The same applied face flux updates both sides of every internal interface.

Monotonized-central MUSCL reconstruction of depth, free surface and velocity is followed by the
hydrostatic reconstruction of Audusse et al. (2004), HLL fluxes, and SSPRK2.
Exact fixed-depth semiimplicit Manning substeps surround the hyperbolic step
(Strang splitting). A donor draining-time limiter changes *shared fluxes*,
never water already stored. Overflow from a compartment is an explicit,
accounted transfer to its absorbing collector: the predictor stage is bounded
for pressure evaluation and the final integrated compartment balance is
projected once onto the physical capacity. Channel overtopping is rejected.

References: doi:10.1137/S1064827503431090; Clawpack's shallow-water HLL chapter.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path

import numpy as np


GRAVITY = 9.81
ENGINE_VERSION = "0.7.0-fv-development"
_LOADED_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_EPS = np.finfo(float).eps


class _Failure(Exception):
    def __init__(self, code, message, path="$", status="invalid_contract"):
        super().__init__(message)
        self.code, self.path, self.status = code, path, status


def _number(value, name, *, minimum=None, maximum=None, integer=False):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.number)) or not math.isfinite(value):
        raise _Failure("finite_number_required", f"{name} must be a finite number.", name)
    if (minimum is not None and value < minimum) or (maximum is not None and value > maximum) or (integer and int(value) != value):
        raise _Failure("outside_envelope", f"{name} is outside its bounded numerical envelope.", name)
    return float(value)


class StorageCurve:
    """Exact integral/inverse of positive piecewise-linear stage-area data.

    Stages and volumes are restricted to the supplied table. No extrapolation
    or numerical minimum area is used. Scalar and numpy-array queries work.
    """

    def __init__(self, stage_area):
        a = np.asarray(stage_area, dtype=float)
        if a.ndim != 2 or a.shape[1] != 2 or not 2 <= len(a) <= 100 or not np.isfinite(a).all():
            raise ValueError("stage_area must have 2 to 100 finite [stage, area] rows")
        if np.any(np.diff(a[:, 0]) <= 0) or np.any(a[:, 1] <= 0):
            raise ValueError("stages must increase strictly and areas must be positive")
        self.stages = a[:, 0].copy()
        self.areas = a[:, 1].copy()
        self.slopes = np.diff(self.areas) / np.diff(self.stages)
        self.volumes = np.r_[0., np.cumsum(.5 * (self.areas[1:] + self.areas[:-1]) * np.diff(self.stages))]
        self.capacity_m3 = float(self.volumes[-1])

    @staticmethod
    def _result(value):
        return float(value) if np.ndim(value) == 0 else value

    def _stage_query(self, stage):
        s = np.asarray(stage, dtype=float)
        if not np.isfinite(s).all() or np.any(s < self.stages[0]) or np.any(s > self.stages[-1]):
            raise ValueError("stage lies outside the supplied storage table")
        i = np.minimum(np.searchsorted(self.stages, s, side="right") - 1, len(self.stages) - 2)
        return s, i

    def volume(self, stage):
        s, i = self._stage_query(stage)
        d = s - self.stages[i]
        return self._result(self.volumes[i] + self.areas[i] * d + .5 * self.slopes[i] * d * d)

    def area(self, stage):
        s, i = self._stage_query(stage)
        return self._result(self.areas[i] + self.slopes[i] * (s - self.stages[i]))

    def stage(self, volume):
        v = np.asarray(volume, dtype=float)
        if not np.isfinite(v).all() or np.any(v < 0) or np.any(v > self.capacity_m3):
            raise ValueError("volume lies outside the supplied storage table")
        i = np.minimum(np.searchsorted(self.volumes, v, side="right") - 1, len(self.stages) - 2)
        d = v - self.volumes[i]
        # Rationalized positive root is stable for zero or negative area slope.
        rise = 2 * d / (self.areas[i] + np.sqrt(self.areas[i] ** 2 + 2 * self.slopes[i] * d))
        ans = self.stages[i] + rise
        ans = np.where(v == self.capacity_m3, self.stages[-1], ans)
        return self._result(ans)


def manning_friction(h, q, B, n, dt):
    """Exact fixed-depth Manning damping of unit discharge; no mass change.

    R=B*h/(B+2*h), dq/dt=-g*n**2*q*abs(q)/(h*R**(4/3)).
    Zero-depth momentum is zero; a zero roughness or zero time is the identity
    on wet cells. Inputs are scalar or broadcastable arrays.
    """
    h, q = np.broadcast_arrays(np.asarray(h, dtype=float), np.asarray(q, dtype=float))
    if not np.isfinite(h).all() or not np.isfinite(q).all() or np.any(h < 0):
        raise ValueError("friction requires finite nonnegative depth and finite momentum")
    for val, label in ((B, "width"), (n, "roughness"), (dt, "time")):
        if not math.isfinite(val) or val < 0 or (label == "width" and val == 0):
            raise ValueError(f"invalid friction {label}")
    ans = np.zeros_like(q)
    wet = h > 0
    if n == 0 or dt == 0:
        ans[wet] = q[wet]
    else:
        active = wet & (q != 0)
        ha, qa = h[active], q[active]
        radius = ha / (1 + 2 * ha / B)
        denominator = ha * radius ** (4. / 3.)
        damping = np.divide(dt * GRAVITY * n * n * np.abs(qa), denominator,
                            out=np.zeros_like(qa), where=denominator > 0)
        tiny = denominator == 0
        if np.any(tiny):
            # A positive subnormal wet film is retained as water. Evaluate its
            # friction without 0/0 or creating a numerical dry-water cutoff.
            log_damping = (math.log(dt) + math.log(GRAVITY) + 2 * math.log(n)
                           + np.log(np.abs(qa[tiny])) - np.log(ha[tiny])
                           - (4. / 3.) * (np.log(ha[tiny]) - np.log1p(2 * ha[tiny] / B)))
            with np.errstate(over="ignore"):
                damping[tiny] = np.exp(log_damping)
        ans[active] = qa / (1 + damping)
    return float(ans) if ans.ndim == 0 else ans


@dataclass
class _Channel:
    id: str
    from_node: str
    to_node: str
    length: float
    width: float
    z0: float
    z1: float
    height: float
    roughness: float
    count: int

    def __post_init__(self):
        self.dx = self.length / self.count
        self.x = (np.arange(self.count) + .5) * self.dx
        self.bed = self.z0 + (self.z1 - self.z0) * self.x / self.length


def _series(raw, duration, name, *, nonnegative=False):
    a = np.asarray(raw, dtype=float)
    if a.ndim != 2 or a.shape[1] != 2 or len(a) < 2 or not np.isfinite(a).all():
        raise _Failure("invalid_timeseries", "Provide finite [time, value] pairs.", name)
    if np.any(np.diff(a[:, 0]) <= 0) or a[0, 0] != 0 or a[-1, 0] != duration or (nonnegative and np.any(a[:, 1] < 0)):
        raise _Failure("invalid_timeseries", "Series must increase from zero to the exact horizon, with nonnegative external inflows.", name)
    return a


def _minmod(a, b):
    same_sign = ((a > 0) & (b > 0)) | ((a < 0) & (b < 0))
    return np.where(same_sign, np.copysign(np.minimum(np.abs(a), np.abs(b)), a), 0.)


def _mc(a, b):
    """Standard monotonized-central TVD slope (no fitted limiter parameter)."""
    return _minmod(.5 * (a + b), _minmod(2 * a, 2 * b))


def _velocity(h, q):
    return np.divide(q, h, out=np.zeros_like(q), where=h > 0)


def _invariant_contraction(h, q, dh, dq, lower, upper):
    """Same paired invariant bisection, batched and restricted to troubled cells.

    Each cell's calculation is independent. The initial check includes every
    cell; only cells failing that check require the same 32 feasible-bracket
    bisections. Batching the two signs preserves each arithmetic expression.
    """
    signs = np.array([-1., 1.])[:, None]

    def admissible(theta, h, q, dh, dq, lower, upper):
        hf = h[None, :] + signs * theta[None, :] * dh[None, :]
        qf = q[None, :] + signs * theta[None, :] * dq[None, :]
        pressure = 2 * hf * np.sqrt(GRAVITY * hf)
        high, low = upper[None, :] * hf, lower[None, :] * hf
        rounding = 16 * _EPS * (np.abs(qf) + pressure + np.abs(high) + np.abs(low))
        okay = (qf + pressure <= high + rounding) & (qf - pressure >= low - rounding)
        return okay[0] & okay[1]

    theta = np.ones_like(h)
    troubled = ~admissible(theta, h, q, dh, dq, lower, upper)
    if np.any(troubled):
        h, q, dh, dq, lower, upper = (v[troubled] for v in (h, q, dh, dq, lower, upper))
        low, high = np.zeros_like(h), np.ones_like(h)
        for _ in range(32):
            middle = .5 * (low + high)
            good = admissible(middle, h, q, dh, dq, lower, upper)
            low = np.where(good, middle, low)
            high = np.where(good, high, middle)
        theta[troubled] = low
    return theta


def _hll(hl, ul, hr, ur):
    cl, cr = np.sqrt(GRAVITY * hl), np.sqrt(GRAVITY * hr)
    sl, sr = ul - cl, ur + cr
    wet = (hl > 0) & (hr > 0) & (ur - ul < 2 * (cl + cr))
    if np.any(wet):
        # Shock-aware HLL wave bounds from the exact star-depth equation.
        # Roe-average bounds have a discontinuous almost-dry limit: their
        # right-going bound tends cL/sqrt(2), although the shock speed tends
        # 2*cL as hR tends zero. That produces an artificial slow wet front.
        indices = np.flatnonzero(wet)
        with np.errstate(over="ignore"):
            kinetic_head = ((ul[wet] - ur[wet]) / math.sqrt(GRAVITY)) ** 2
        if not np.isfinite(kinetic_head).all():
            raise _Failure("riemann_velocity_range", "Riemann velocity exceeds finite numerical range.", "$", "numerical_failure")
        # Kinetic-head scaling also bounds the dimensionless velocity jump in
        # almost-vacuum films, where scaling only by depth can overflow.
        scale = np.maximum(np.maximum(hl[wet], hr[wet]), kinetic_head)
        a, b = hl[wet] / scale, hr[wet] / scale
        lost_left, lost_right = a == 0, b == 0
        sl[indices[lost_left]] = ur[indices[lost_left]] - 2 * cr[indices[lost_left]]
        sr[indices[lost_right]] = ul[indices[lost_right]] + 2 * cl[indices[lost_right]]
        representable = ~(lost_left | lost_right)
        indices = indices[representable]
        a, b, scale = a[representable], b[representable], scale[representable]
        cs = np.sqrt(GRAVITY * scale)
        du = (ur[indices] - ul[indices]) / cs
        root = (.5 * (np.sqrt(a) + np.sqrt(b)) - .25 * du) ** 2
        shock = root > np.minimum(a, b)
        if np.any(shock):
            r = root[shock]
            ga = np.sqrt(.5 * (1 + a[shock] / r)) / np.sqrt(a[shock])
            gb = np.sqrt(.5 * (1 + b[shock] / r)) / np.sqrt(b[shock])
            root[shock] = (ga * a[shock] + gb * b[shock] - du[shock]) / (ga + gb)

        def wave(depth, side):
            rare = depth <= side
            value, derivative = np.empty_like(depth), np.empty_like(depth)
            value[rare] = 2 * (np.sqrt(depth[rare]) - np.sqrt(side[rare]))
            derivative[rare] = 1 / np.sqrt(depth[rare])
            hot = ~rare
            if np.any(hot):
                d, s = depth[hot], side[hot]
                coeff = np.sqrt(.5 * (1 + s / d)) / np.sqrt(s)
                value[hot] = (d - s) * coeff
                derivative[hot] = coeff * (1 - .5 * ((d - s) / d) * (s / (d + s)))
            return value, derivative

        for _ in range(24):
            fa, da = wave(root, a)
            fb, db = wave(root, b)
            change = (fa + fb + du) / (da + db)
            proposed = root - change
            proposed = np.where(proposed > 0, proposed, .5 * root)
            converged = np.abs(proposed - root) <= 1e-10 * root
            root = proposed
            if np.all(converged):
                break
        else:
            raise _Failure("riemann_iteration_limit", "Shock-aware HLL wave estimates did not converge within 24 iterations.", "$", "numerical_failure")
        left_speed, right_speed = np.sqrt(a), np.sqrt(b)
        shock_left, shock_right = root > a, root > b
        left_speed[shock_left] = (root[shock_left] / np.sqrt(a[shock_left])) * np.sqrt(.5 * (1 + a[shock_left] / root[shock_left]))
        right_speed[shock_right] = (root[shock_right] / np.sqrt(b[shock_right])) * np.sqrt(.5 * (1 + b[shock_right] / root[shock_right]))
        sl[indices] = ul[indices] - cs * left_speed
        sr[indices] = ur[indices] + cs * right_speed
    # Exact rarefaction edge estimates where one side is dry.
    sl = np.where(hl == 0, ur - 2 * cr, sl)
    sr = np.where(hr == 0, ul + 2 * cl, sr)
    sl, sr = np.minimum(sl, 0.), np.maximum(sr, 0.)
    ql, qr = hl * ul, hr * ur
    fl, fr = ql * ul + .5 * GRAVITY * hl * hl, qr * ur + .5 * GRAVITY * hr * hr
    den = sr - sl
    mass = np.divide(sr * ql - sl * qr + sl * sr * (hr - hl), den, out=np.zeros_like(hl), where=den > 0)
    momentum = np.divide(sr * fl - sl * fr + sl * sr * (qr - ql), den, out=np.zeros_like(hl), where=den > 0)
    return mass, momentum, float(np.max(np.maximum(-sl, sr)))


def _faces(channel, h, q, stages, modes, order):
    """Return numerical flux and local hydrostatic terms for one channel."""
    c = channel
    u = _velocity(h, q)
    eta = h + c.bed
    hp, ep, up = np.empty(c.count + 2), np.empty(c.count + 2), np.empty(c.count + 2)
    hp[1:-1], ep[1:-1], up[1:-1] = h, eta, u
    endpoints = ((c.from_node, 0, 0, c.z0, c.bed[0] - (c.bed[1] - c.bed[0])),
                 (c.to_node, -1, -1, c.z1, c.bed[-1] + (c.bed[-1] - c.bed[-2])))
    for nid, p, j, face_bed, ghost_bed in endpoints:
        mode = modes.get(nid, {}).get("mode", "reservoir")
        if mode == "wall":
            hp[p], up[p] = max(0., eta[j] - ghost_bed), -u[j]
        elif mode == "transmissive":
            hp[p], up[p] = h[j], u[j]
        elif mode == "fixed_velocity":
            hp[p], up[p] = max(0., stages[nid] - face_bed), modes[nid]["velocity_m_s"]
        else:
            hp[p], up[p] = max(0., stages[nid] - ghost_bed), 0.
        ep[p] = ghost_bed + hp[p]
    if order == 2:
        sh = _mc(hp[1:-1] - hp[:-2], hp[2:] - hp[1:-1])
        se = _mc(ep[1:-1] - ep[:-2], ep[2:] - ep[1:-1])
        su = _mc(up[1:-1] - up[:-2], up[2:] - up[1:-1])
    else:
        sh, se, su = np.zeros_like(h), np.zeros_like(h), np.zeros_like(h)
    padded_c = 2 * np.sqrt(GRAVITY * hp)
    invariant_upper = np.maximum.reduce((up[:-2] + padded_c[:-2], up[1:-1] + padded_c[1:-1], up[2:] + padded_c[2:]))
    invariant_lower = np.minimum.reduce((up[:-2] - padded_c[:-2], up[1:-1] - padded_c[1:-1], up[2:] - padded_c[2:]))
    hm, hp = h - .5 * sh, h + .5 * sh
    # Depth-weighted velocity slopes retain the cell mean of momentum:
    # (hm*um + hp*up)/2 == h*u. Symmetric primitive-velocity slopes instead
    # introduce a spurious sh*su/4 contribution, important at a wet/dry front.
    wp = np.divide(hm, h, out=np.zeros_like(h), where=h > 0)
    # Apply the joint physical invariant constraint below, rather than also
    # restricting velocity to adjacent cell values. The latter independent
    # primitive bound forbids physically admissible shallow/high-speed states.
    dq = .5 * sh * u + .5 * wp * hp * su
    theta = _invariant_contraction(h, q, .5 * sh, dq, invariant_lower, invariant_upper) if order == 2 else np.ones_like(h)
    sh, se, dq = theta * sh, theta * se, theta * dq
    hm, hp = h - .5 * sh, h + .5 * sh
    em, ep = eta - .5 * se, eta + .5 * se
    zm, zp = em - hm, ep - hp
    um, up = _velocity(hm, q - dq), _velocity(hp, q + dq)
    hl, hr = np.empty(c.count + 1), np.empty(c.count + 1)
    zl, zr, ul, ur = (np.empty_like(hl) for _ in range(4))
    hl[1:], zl[1:], ul[1:] = hp, zp, up
    hr[:-1], zr[:-1], ur[:-1] = hm, zm, um
    for nid, face, cell, face_bed, _ in endpoints:
        mode = modes.get(nid, {}).get("mode", "reservoir")
        if face == 0:
            hi, zi, ui = hr[0], zr[0], ur[0]
        else:
            hi, zi, ui = hl[-1], zl[-1], ul[-1]
        if mode in ("wall", "transmissive"):
            hb, zb, ub = hi, zi, -ui if mode == "wall" else ui
        else:
            hb, zb = max(0., stages[nid] - face_bed), face_bed
            ub = modes.get(nid, {}).get("velocity_m_s", 0.)
        if face == 0:
            hl[0], zl[0], ul[0] = hb, zb, ub
        else:
            hr[-1], zr[-1], ur[-1] = hb, zb, ub
    zstar = np.maximum(zl, zr)
    hls, hrs = np.maximum(0., hl + zl - zstar), np.maximum(0., hr + zr - zstar)
    mass, momentum, speed = _hll(hls, ul, hrs, ur)
    # This algebraic form combines cell pressure and bed source, reducing
    # cancellation in lake-at-rest states without modifying conserved water.
    return {"mass": mass, "momentum": momentum, "pressure_left": .5 * GRAVITY * hls * hls,
            "pressure_right": .5 * GRAVITY * hrs * hrs,
            "surface_source": -GRAVITY * .5 * (hm + hp) * se / c.dx,
            "speed": max(speed, float(np.max(np.abs(u) + np.sqrt(GRAVITY * h))))}


def _drain_factor(available, demand):
    available, demand = np.broadcast_arrays(available, demand)
    factor = np.ones_like(available, dtype=float)
    limited = demand > available
    factor[limited] = available[limited] / demand[limited] * (1 - 16 * _EPS)
    return factor


def _snapshot(channels, state, volumes):
    node = {k: float(v) for k, v in volumes.items()}
    link = {c.id: float(np.sum(state[c.id][0]) * c.width * c.dx) for c in channels}
    return node, link, math.fsum(node.values()) + math.fsum(link.values())


def _balance(first, last):
    incoming = last["cumulative_external_inflow_m3"] - first["cumulative_external_inflow_m3"]
    back = last["cumulative_receiving_backflow_m3"] - first["cumulative_receiving_backflow_m3"]
    discharge = last["cumulative_discharge_m3"] - first["cumulative_discharge_m3"]
    spill = last["cumulative_spill_m3"] - first["cumulative_spill_m3"]
    residual = first["storage_m3"] + incoming + back - discharge - spill - last["storage_m3"]
    tolerance = max(1e-6, .01 * (first["storage_m3"] + incoming + back))
    return {"start_s": first["elapsed_s"], "end_s": last["elapsed_s"],
            "initial_storage_m3": first["storage_m3"], "final_storage_m3": last["storage_m3"],
            "external_inflow_m3": incoming, "receiving_backflow_m3": back,
            "discharge_m3": discharge, "spill_m3": spill,
            "residual_m3": residual, "tolerance_m3": tolerance, "passed": abs(residual) <= tolerance}


def simulate(network, *, cells_per_channel=64, max_step_s=0.01, cfl=0.4,
             split_times=(50.0,), initial_state=None, boundary_modes=None,
             spatial_order=2, maximum_steps=300000, state_observer=None):
    """Run the bounded FV model and return its complete applied-water ledger.

    ``nodes`` contains internal compartments; ``boundaries`` contains disjoint
    prescribed receiving reservoirs. Channel endpoints reference either set.
    ``initial_state`` and non-reservoir ``boundary_modes`` are analytical-test
    hooks, deliberately unavailable in the supplied-data adapter. The optional
    ``state_observer`` receives copied channel arrays at every actual endpoint
    for independent analytical instrumentation; it cannot mutate solver state.
    """
    result = {"valid": False, "status": "invalid_contract", "errors": [], "timeseries": [],
              "routing_trace": [], "final_state": {}, "diagnostics": {}, "phase_balances": {}}
    try:
        if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED_SOURCE_SHA256:
            raise _Failure("source_changed", "Loaded solver source differs from the file on disk.")
        return _simulate(network, cells_per_channel, max_step_s, cfl, split_times, initial_state,
                         boundary_modes, spatial_order, maximum_steps, result, state_observer)
    except _Failure as exc:
        result["status"] = exc.status
        result["errors"].append({"code": exc.code, "path": exc.path, "message": str(exc)})
    except (ValueError, TypeError, KeyError, OverflowError, IndexError) as exc:
        result["errors"].append({"code": "invalid_core_input", "path": "$", "message": str(exc)})
    return result


def _simulate(network, count, max_dt, cfl, split_times, initial, boundary_modes, order, max_steps, result, observer):
    if observer is not None and not callable(observer):
        raise _Failure("observer_required_callable", "Analytical state_observer must be callable or None.")
    count = int(_number(count, "cells_per_channel", minimum=4, maximum=4096, integer=True))
    max_dt = _number(max_dt, "max_step_s", minimum=1e-8, maximum=1.)
    cfl = _number(cfl, "cfl", minimum=1e-4, maximum=.45)
    max_steps = int(_number(max_steps, "maximum_steps", minimum=1, maximum=300000, integer=True))
    if order not in (1, 2) or isinstance(order, bool):
        raise _Failure("spatial_order", "Only first or second spatial order is supported.")
    duration = _number(network["duration_s"], "duration_s", minimum=1e-8, maximum=3600)
    report_dt = _number(network["report_step_s"], "report_step_s", minimum=1e-8, maximum=duration)
    if duration / report_dt > 10000:
        raise _Failure("report_budget", "At most 10000 reporting intervals are supported.")
    nodes, boundaries = network["nodes"], network["boundaries"]
    if not isinstance(nodes, dict) or not isinstance(boundaries, dict) or set(nodes) & set(boundaries):
        raise _Failure("endpoint_inventory", "Storage nodes and boundary reservoirs must be disjoint dictionaries.")
    if len(nodes) + len(boundaries) > 30 or not isinstance(network["channels"], list) or len(network["channels"]) > 30:
        raise _Failure("network_budget", "At most 30 nodes/boundaries and 30 channels are supported.")
    curves = {}
    for nid, n in nodes.items():
        curves[nid] = StorageCurve(n["stage_area"])
        if curves[nid].stages[0] != n["invert_m"] or curves[nid].stages[-1] != n["maximum_stage_m"]:
            raise _Failure("storage_extent", "Storage curve must exactly span invert to overflow stage.", nid)
    boundary_series = {k: _series(v, duration, "boundaries." + k) for k, v in boundaries.items()}
    inflows = {k: _series(v, duration, "inflows." + k, nonnegative=True) for k, v in network["inflows"].items()}
    if not set(inflows) <= set(nodes):
        raise _Failure("inflow_inventory", "External inflows must enter a storage compartment.")
    modes = {}
    for nid, mode in (boundary_modes or {}).items():
        mode = {"mode": mode} if isinstance(mode, str) else dict(mode)
        if nid not in boundaries or mode.get("mode") not in ("reservoir", "wall", "transmissive", "fixed_velocity"):
            raise _Failure("boundary_mode", "Analytical boundary modes require a known boundary endpoint.", str(nid))
        if mode["mode"] == "fixed_velocity":
            _number(mode.get("velocity_m_s"), "velocity_m_s")
        modes[nid] = mode
    channels, ids = [], set()
    for data in network["channels"]:
        ident = data["id"]
        if ident in ids or not isinstance(ident, str):
            raise _Failure("channel_id", "Channel IDs must be distinct strings.")
        ids.add(ident)
        for key in ("entrance_loss_coefficient", "exit_loss_coefficient", "average_loss_coefficient", "inlet_offset_m", "outlet_offset_m"):
            if data.get(key, 0) != 0:
                raise _Failure("unsupported_geometry", "Offsets and minor losses are unsupported.", ident)
        if data.get("shape", "rectangular") not in ("rectangular", "RECT_OPEN"):
            raise _Failure("unsupported_geometry", "Only rectangular open channels are supported.", ident)
        for endpoint, zkey in (("from_node", "inlet_invert_m"), ("to_node", "outlet_invert_m")):
            nid = data[endpoint]
            if nid not in nodes and nid not in boundaries:
                raise _Failure("unknown_endpoint", "Channel endpoint is missing.", ident)
            if nid in nodes and data[zkey] != nodes[nid]["invert_m"]:
                raise _Failure("unsupported_offset", "Channel ends must match the adjoining compartment invert.", ident)
        if data["from_node"] == data["to_node"]:
            raise _Failure("self_loop", "A channel must have two distinct endpoints.", ident)
        c = _Channel(ident, data["from_node"], data["to_node"],
                     _number(data["length_m"], ident + ".length", minimum=1e-6, maximum=10000),
                     _number(data["width_m"], ident + ".width", minimum=1e-8, maximum=100),
                     _number(data["inlet_invert_m"], ident + ".inlet"),
                     _number(data["outlet_invert_m"], ident + ".outlet"),
                     _number(data["height_m"], ident + ".height", minimum=1e-8, maximum=100),
                     _number(data["roughness_n"], ident + ".roughness", minimum=0, maximum=1), count)
        channels.append(c)
    if len(channels) * count > 40000:
        raise _Failure("cell_budget", "At most 40000 channel cells are supported.")
    initial = initial or {}
    if not set(initial.get("nodes", {})) <= set(nodes) or not set(initial.get("channels", {})) <= ids:
        raise _Failure("initial_inventory", "Initial state names unknown compartments or channels.")
    volumes = {}
    for nid in nodes:
        spec = initial.get("nodes", {}).get(nid, {})
        if "stage_m" in spec and "volume_m3" in spec:
            raise _Failure("ambiguous_initial_state", "Specify one initial stage or volume.", nid)
        volumes[nid] = curves[nid].volume(spec["stage_m"]) if "stage_m" in spec else float(spec.get("volume_m3", 0.))
        curves[nid].stage(volumes[nid])
    state = {}
    for c in channels:
        spec = initial.get("channels", {}).get(c.id, {})
        h = np.broadcast_to(np.asarray(spec.get("depth_m", 0.), dtype=float), (count,)).copy()
        q = np.broadcast_to(np.asarray(spec.get("unit_discharge_m2_s", 0.), dtype=float), (count,)).copy()
        if not np.isfinite(h).all() or not np.isfinite(q).all() or np.any(h < 0) or np.any((h == 0) & (q != 0)):
            raise _Failure("invalid_initial_state", "Initial water and momentum must be finite, nonnegative depth, zero momentum when dry.", c.id)
        state[c.id] = h, q
    split = sorted({_number(t, "split_times", minimum=0, maximum=3600) for t in split_times if 0 < t < duration})
    reports = [float(i * report_dt) for i in range(1, int(math.floor(duration / report_dt)) + 1) if i * report_dt < duration] + [duration]
    events = sorted(set(reports + split + [duration] + [float(t) for a in list(inflows.values()) + list(boundary_series.values()) for t in a[:, 0] if t > 0]))
    report_set, phase_set = set(reports), set(split + [duration])

    def stages_at(t, v):
        return {**{k: curves[k].stage(x) for k, x in v.items()},
                **{k: float(np.interp(t, a[:, 0], a[:, 1])) for k, a in boundary_series.items()}}

    def forcing(t):
        return {k: float(np.interp(t, a[:, 0], a[:, 1])) if (a := inflows.get(k)) is not None else 0. for k in nodes}

    def guard(s, v, stage):
        for nid, value in v.items():
            if not math.isfinite(value) or value < 0 or value > curves[nid].capacity_m3:
                raise _Failure("invalid_storage", "Compartment water left its physical bounds.", nid, "numerical_failure")
        for c in channels:
            h, q = s[c.id]
            if not np.isfinite(h).all() or not np.isfinite(q).all() or np.any(h < 0):
                raise _Failure("invalid_state", "Nonfinite or negative water state; no clipping was applied.", c.id, "numerical_failure")
            if float(np.max(h)) > c.height * (1 + 32 * _EPS):
                raise _Failure("unsupported_channel_overtopping", "Channel water exceeds the represented open-channel height.", c.id, "scope_exceeded")
            for nid, z in ((c.from_node, c.z0), (c.to_node, c.z1)):
                if modes.get(nid, {}).get("mode", "reservoir") not in ("wall", "transmissive") and stage[nid] - z > c.height * (1 + 32 * _EPS):
                    raise _Failure("unsupported_channel_overtopping", "Endpoint stage exceeds the represented channel wall height.", c.id, "scope_exceeded")

    def fluxes(t, s, v):
        stage = stages_at(t, v)
        guard(s, v, stage)
        return {c.id: _faces(c, *s[c.id], stage, modes, order) for c in channels}, stage

    def euler(t, s, v, dt, faces):
        incoming = forcing(t)
        node_demand = {k: 0. for k in nodes}
        cell_factor = {}
        for c in channels:
            f = faces[c.id]["mass"]
            outgoing = np.maximum(f[1:], 0.) + np.maximum(-f[:-1], 0.)
            cell_factor[c.id] = _drain_factor(s[c.id][0] * c.dx, dt * outgoing)
            if c.from_node in nodes:
                node_demand[c.from_node] += max(float(f[0] * c.width), 0.)
            if c.to_node in nodes:
                node_demand[c.to_node] += max(float(-f[-1] * c.width), 0.)
        node_factor = {k: float(_drain_factor(v[k] + dt * incoming[k], dt * node_demand[k])) for k in nodes}
        rates = dict(incoming)
        updated, upvol, downvol = {}, {}, {}
        exchanges = {k: 0. for k in boundaries}
        limiter_count = 0
        for c in channels:
            face = faces[c.id]
            f = face["mass"]
            left_factor = np.r_[node_factor.get(c.from_node, 1.), cell_factor[c.id]]
            right_factor = np.r_[cell_factor[c.id], node_factor.get(c.to_node, 1.)]
            scale = np.where(f >= 0, left_factor, right_factor)
            limiter_count += int(np.count_nonzero(scale < 1))
            fm, fq = f * scale, face["momentum"] * scale
            h, q = s[c.id]
            hnew = h + dt / c.dx * (fm[:-1] - fm[1:])
            qnew = q + dt * (-(fq[1:] - face["pressure_left"][1:] - fq[:-1] + face["pressure_right"][:-1]) / c.dx + face["surface_source"])
            qnew = np.where(hnew == 0, 0., qnew)
            updated[c.id] = hnew, qnew
            up, down = float(fm[0] * c.width), float(fm[-1] * c.width)
            upvol[c.id], downvol[c.id] = dt * up, dt * down
            if c.from_node in nodes:
                rates[c.from_node] -= up
            else:
                exchanges[c.from_node] -= dt * up
            if c.to_node in nodes:
                rates[c.to_node] += down
            else:
                exchanges[c.to_node] += dt * down
        vnew, spill = {}, {}
        for k in nodes:
            trial = v[k] + dt * rates[k]
            excess = max(0., trial - curves[k].capacity_m3)
            vnew[k], spill[k] = (curves[k].capacity_m3 if excess > 0 else trial), excess
        ledger = {"external": {k: dt * x for k, x in incoming.items()}, "boundary": exchanges,
                  "upstream": upvol, "downstream": downvol, "node_rate": rates,
                  "limited_faces": limiter_count}
        return updated, vnew, ledger

    total = {"external_inflow": 0., "receiving_backflow": 0., "discharge": 0., "spill": 0.}
    spill_totals, back_totals, discharge_totals = ({k: 0. for k in nodes}, {k: 0. for k in boundaries}, {k: 0. for k in boundaries})
    maximum_stage = stages_at(0., volumes)
    maximum_cfl, minimum_depth, limited_count, rejected_steps = 0., min([float(np.min(h)) for h, _ in state.values()] or [0.]), 0, 0
    step = 0
    t, event_index = 0., 0
    report_spill = {k: 0. for k in nodes}
    last_report_time = 0.

    def trace_row(dt=0., first=None, second=None, actual_cfl=0., applied_spill=None):
        ns, ls, storage = _snapshot(channels, state, volumes)
        row = {"elapsed_s": t, "time_s": t, "dt_s": dt, "storage_m3": storage,
               "node_storage_m3": ns, "link_storage_m3": ls, "maximum_cfl": actual_cfl,
               "minimum_depth_m": min([float(np.min(h)) for h, _ in state.values()] +
                                      [curves[k].stage(v) - nodes[k]["invert_m"] for k, v in volumes.items()] or [0.]),
               **{"cumulative_" + k + "_m3": float(v) for k, v in total.items()}}
        for k in total:
            row["interval_" + k + "_m3"] = 0.
        empty = {"upstream": {c.id: 0. for c in channels}, "downstream": {c.id: 0. for c in channels},
                 "external": {k: 0. for k in nodes}, "spill": {k: 0. for k in nodes}, "boundary": {k: 0. for k in boundaries}}
        first, second = first or empty, second or empty
        for label, field in (("upstream", "interval_channel_upstream_m3"), ("downstream", "interval_channel_downstream_m3"),
                             ("external", "interval_external_by_node_m3")):
            row[field] = {k: .5 * (first[label][k] + second[label][k]) for k in first[label]}
        row["interval_external_inflow_by_node_m3"] = dict(row["interval_external_by_node_m3"])
        row["interval_spill_by_node_m3"] = dict(applied_spill or {k: 0. for k in nodes})
        row["boundary_exchange_stage_1_m3"] = {k: .5 * v for k, v in first["boundary"].items()}
        row["boundary_exchange_stage_2_m3"] = {k: .5 * v for k, v in second["boundary"].items()}
        row["interval_receiving_by_boundary_m3"] = {k: .5 * (max(-first["boundary"][k], 0.) + max(-second["boundary"][k], 0.)) for k in boundaries}
        row["interval_discharge_by_boundary_m3"] = {k: .5 * (max(first["boundary"][k], 0.) + max(second["boundary"][k], 0.)) for k in boundaries}
        for label, field in (("external_inflow", "interval_external_by_node_m3"), ("receiving_backflow", "interval_receiving_by_boundary_m3"),
                             ("discharge", "interval_discharge_by_boundary_m3"), ("spill", "interval_spill_by_node_m3")):
            row["interval_" + label + "_m3"] = math.fsum(row[field].values())
        return row

    initial_faces, _ = fluxes(0., state, volumes)
    row0 = trace_row()
    initial_storage = row0["storage_m3"]
    row0.update(residual_m3=0., tolerance_m3=max(1e-6, .01 * initial_storage), conservation_passed=True)
    result["routing_trace"].append(row0)
    if observer is not None:
        observer({"time_s": t, "channels": {k: {"depth_m": h.copy(), "unit_discharge_m2_s": q.copy()} for k, (h, q) in state.items()}})
    phase_start = row0

    def report(faces, stage):
        nonlocal last_report_time
        ns, ls, storage = _snapshot(channels, state, volumes)
        point_out = {k: 0. for k in boundaries}
        link_flow = {}
        for c in channels:
            f = faces[c.id]["mass"] * c.width
            link_flow[c.id] = float(np.interp(.5 * c.length, np.linspace(0., c.length, count + 1), f))
            if c.from_node in boundaries:
                point_out[c.from_node] -= float(f[0])
            if c.to_node in boundaries:
                point_out[c.to_node] += float(f[-1])
        interval = t - last_report_time
        result["timeseries"].append({"elapsed_s": t, "time_s": t, "stage_m": dict(stage), "link_flow_m3_s": link_flow,
              "storage_m3": storage, "node_storage_m3": ns, "link_storage_m3": ls,
              "outflow_m3_s": point_out, "inflow_m3_s": forcing(t),
              "spill_m3_s": {k: v / interval if interval > 0 else 0. for k, v in report_spill.items()}})
        for k in report_spill:
            report_spill[k] = 0.
        last_report_time = t

    report(initial_faces, stages_at(0., volumes))
    failure = None
    try:
        while t < duration:
            if step >= max_steps:
                raise _Failure("maximum_steps", "Maximum accepted steps reached before the requested horizon.", "$", "step_limit")
            event = events[event_index]
            faces0, _ = fluxes(t, state, volumes)
            rate0 = max([f["speed"] / c.dx for c in channels if (f := faces0[c.id])] or [0.])
            dt = min(max_dt, event - t, .9 * cfl / rate0 if rate0 > 0 else max_dt)
            for attempt in range(32):
                if not dt > 0 or t + dt == t:
                    raise _Failure("step_underflow", "Stable time step cannot advance the clock.", "$", "numerical_failure")
                half = {c.id: (state[c.id][0], manning_friction(*state[c.id], c.width, c.roughness, .5 * dt)) for c in channels}
                fa, _ = fluxes(t, half, volumes)
                sa, va, la = euler(t, half, volumes, dt, fa)
                fb, _ = fluxes(t + dt, sa, va)
                rate = max([max(fa[c.id]["speed"], fb[c.id]["speed"]) / c.dx for c in channels] or [0.])
                actual_cfl = dt * rate
                if actual_cfl <= cfl * (1 + 1e-12):
                    break
                rejected_steps += 1
                dt *= .9 * cfl / actual_cfl
            else:
                raise _Failure("step_retry_limit", "CFL control could not accept a step within 32 attempts.", "$", "numerical_failure")
            sb, vb, lb = euler(t + dt, sa, va, dt, fb)
            candidate = {}
            for c in channels:
                h = .5 * (half[c.id][0] + sb[c.id][0])
                q = .5 * (half[c.id][1] + sb[c.id][1])
                candidate[c.id] = h, manning_friction(h, q, c.width, c.roughness, .5 * dt)
            # The bounded predictor controls stage-2 pressure, but its
            # temporary capacity projection is not an actual collector flux.
            # Integrate the two applied water-transfer rates, then transfer
            # the resulting physical excess to the collector exactly once.
            # This avoids SSP averaging two capped states and inventing spill
            # while the accepted compartment is still below capacity.
            raw_volumes = {k: volumes[k] + .5 * dt * (la["node_rate"][k] + lb["node_rate"][k]) for k in nodes}
            applied_spill = {k: max(0., raw_volumes[k] - curves[k].capacity_m3) for k in nodes}
            new_volumes = {k: curves[k].capacity_m3 if applied_spill[k] > 0 else raw_volumes[k] for k in nodes}
            next_t = t + dt
            if dt == event - t:
                next_t = event
            next_stages = stages_at(next_t, new_volumes)
            guard(candidate, new_volumes, next_stages)
            state, volumes, t = candidate, new_volumes, next_t
            step += 1
            limited_count += la["limited_faces"] + lb["limited_faces"]
            maximum_cfl = max(maximum_cfl, actual_cfl)
            minimum_depth = min(minimum_depth, min([float(np.min(h)) for h, _ in state.values()] or [0.]))
            for k, value in next_stages.items():
                maximum_stage[k] = max(maximum_stage[k], value)
            row = trace_row(dt, la, lb, actual_cfl, applied_spill)
            for k in total:
                total[k] += row["interval_" + k + "_m3"]
                row["cumulative_" + k + "_m3"] = total[k]
            for k in nodes:
                spill_totals[k] += row["interval_spill_by_node_m3"][k]
                report_spill[k] += row["interval_spill_by_node_m3"][k]
            for k in boundaries:
                back_totals[k] += row["interval_receiving_by_boundary_m3"][k]
                discharge_totals[k] += row["interval_discharge_by_boundary_m3"][k]
            residual = initial_storage + total["external_inflow"] + total["receiving_backflow"] - total["discharge"] - total["spill"] - row["storage_m3"]
            tolerance = max(1e-6, .01 * (initial_storage + total["external_inflow"] + total["receiving_backflow"]))
            row.update(residual_m3=residual, tolerance_m3=tolerance, conservation_passed=abs(residual) <= tolerance)
            result["routing_trace"].append(row)
            if observer is not None:
                observer({"time_s": t, "channels": {k: {"depth_m": h.copy(), "unit_discharge_m2_s": q.copy()} for k, (h, q) in state.items()}})
            if abs(residual) > tolerance:
                raise _Failure("conservation_failure", "An actual endpoint exceeded the unchanged water budget.", "$", "numerical_failure")
            if t in phase_set:
                phase = _balance(phase_start, row)
                result["phase_balances"]["phase_" + str(len(result["phase_balances"]) + 1)] = phase
                phase_start = row
                if not phase["passed"]:
                    raise _Failure("phase_conservation_failure", "An exact phase endpoint exceeded the unchanged water budget.", "$", "numerical_failure")
            if t in report_set:
                ff, ss = fluxes(t, state, volumes)
                report(ff, ss)
            if t == event:
                event_index += 1
    except _Failure as exc:
        failure = exc
    result["final_state"] = {"elapsed_s": t, "nodes": {k: {"stage_m": curves[k].stage(v), "volume_m3": v} for k, v in volumes.items()},
         "channels": {c.id: {"x_m": c.x.tolist(), "bed_m": c.bed.tolist(), "depth_m": state[c.id][0].tolist(),
                     "unit_discharge_m2_s": state[c.id][1].tolist(), "dx_m": c.dx} for c in channels}}
    trace = result["routing_trace"]
    result["phase_balances"]["whole"] = _balance(trace[0], trace[-1])
    result["diagnostics"] = {"engine_version": ENGINE_VERSION, "source_sha256": _LOADED_SOURCE_SHA256,
         "completed_duration_s": t, "requested_duration_s": duration, "step_count": step,
         "maximum_steps": max_steps, "cells_per_channel": count, "spatial_order": order,
         "maximum_cfl": maximum_cfl, "requested_cfl": cfl, "max_step_s": max_dt,
         "rejected_cfl_trials": rejected_steps, "limited_face_count": limited_count,
         "minimum_depth_m": minimum_depth, "initial_storage_m3": initial_storage,
         "final_storage_m3": trace[-1]["storage_m3"], "maximum_stage_m": maximum_stage,
         "spill_by_node_m3": spill_totals, "discharge_by_outfall_m3": discharge_totals,
         "backflow_by_outfall_m3": back_totals,
         "maximum_abs_residual_m3": max(abs(r["residual_m3"]) for r in trace),
         "every_endpoint_conservation_passed": all(r["conservation_passed"] for r in trace),
         "initialization": "provided_analytical_state" if initial else "exact_dry_zero_flow",
         "spatial_limiter": "monotonized_central_conservative_local_invariant_contraction",
         "overflow_integration": "capacity_bounded_predictor_and_final_integrated_collector_projection",
         "mass_ledger": "actual_SSPRK2_weighted_applied_face_transfers",
         "reported_spill": "preceding_report_interval_mean",
         **{k + "_m3": float(v) for k, v in total.items()}}
    if failure is not None:
        raise failure
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _LOADED_SOURCE_SHA256:
        raise _Failure("source_changed", "Solver source changed during execution.", "$", "source_changed")
    result.update(valid=True, status="completed")
    return result
