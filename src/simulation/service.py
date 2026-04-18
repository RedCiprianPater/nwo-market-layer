"""
Simulation service — client for the nwo-simulation-api.

Submits a mesh file (STL/3MF) to the simulation backend and returns
physics analysis: torque loads, stress concentrations, collision detection.

Supports MuJoCo and Gazebo backends via the nwo-simulation-api:
  https://github.com/RedCiprianPater/nwo-simulation-api

Closes the autonomous design-test-iterate loop:
  L1 Design → L1 Validate → L6 Simulate → L2 Publish → L3 Print
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import httpx

_SIM_URL     = os.getenv("SIMULATION_API_URL", "http://localhost:8090")
_SIM_KEY     = os.getenv("SIMULATION_API_KEY", "")
_SIM_TIMEOUT = float(os.getenv("SIMULATION_TIMEOUT_SEC", "300"))
_DEFAULT_SIM = os.getenv("DEFAULT_SIMULATOR", "mujoco")


class SimulationStatus(str, Enum):
    pending  = "pending"
    running  = "running"
    complete = "complete"
    failed   = "failed"


@dataclass
class SimulationScenario:
    """What physics scenario to run on the part."""
    simulator: str = "mujoco"          # "mujoco" | "gazebo"
    gravity_ms2: float = 9.81
    applied_force_n: float = 10.0      # Force in Newtons applied to key stress points
    applied_torque_nm: float = 2.0     # Torque in Nm (relevant for joints)
    material_density_kg_m3: float = 1240.0  # PLA default
    youngs_modulus_gpa: float = 3.5    # PLA Young's modulus
    simulation_steps: int = 1000
    check_collision: bool = True


@dataclass
class StressPoint:
    location: list[float]  # [x, y, z] in mm
    stress_mpa: float
    is_critical: bool      # exceeds material yield strength


@dataclass
class SimulationResult:
    job_id: str
    status: SimulationStatus
    simulator: str

    # Physics results
    passed: bool
    max_stress_mpa: float | None = None
    yield_strength_mpa: float | None = None  # Material yield strength
    safety_factor: float | None = None        # yield / max_stress; >1.5 = good
    max_displacement_mm: float | None = None
    natural_frequency_hz: float | None = None
    collision_detected: bool = False

    # Detail
    stress_points: list[StressPoint] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "job_id":              self.job_id,
            "status":              self.status.value,
            "simulator":           self.simulator,
            "passed":              self.passed,
            "max_stress_mpa":      self.max_stress_mpa,
            "yield_strength_mpa":  self.yield_strength_mpa,
            "safety_factor":       self.safety_factor,
            "max_displacement_mm": self.max_displacement_mm,
            "natural_frequency_hz":self.natural_frequency_hz,
            "collision_detected":  self.collision_detected,
            "warnings":            self.warnings,
            "recommendations":     self.recommendations,
            "stress_points":       [
                {"location": p.location, "stress_mpa": p.stress_mpa, "is_critical": p.is_critical}
                for p in self.stress_points
            ],
        }


async def submit_simulation(
    mesh_path: Path | None = None,
    mesh_url: str | None = None,
    part_id: str | None = None,
    scenario: SimulationScenario | None = None,
) -> SimulationResult:
    """
    Submit a mesh to the nwo-simulation-api and wait for results.

    One of mesh_path, mesh_url, or part_id must be provided.
    mesh_url: direct URL to an STL/3MF file (e.g. from Layer 2 gallery)
    part_id:  Layer 2 part ID — the simulation-api will fetch the file itself

    Args:
        mesh_path: Local path to the mesh file
        mesh_url:  URL to fetch the mesh from (Layer 2 gallery URL)
        part_id:   Layer 2 part ID
        scenario:  Physics scenario parameters

    Returns:
        SimulationResult with pass/fail verdict and detailed physics data
    """
    if not any([mesh_path, mesh_url, part_id]):
        raise ValueError("One of mesh_path, mesh_url, or part_id is required")

    sc = scenario or SimulationScenario(simulator=_DEFAULT_SIM)

    headers = {}
    if _SIM_KEY:
        headers["X-API-Key"] = _SIM_KEY

    payload: dict[str, Any] = {
        "simulator":              sc.simulator,
        "gravity_ms2":            sc.gravity_ms2,
        "applied_force_n":        sc.applied_force_n,
        "applied_torque_nm":      sc.applied_torque_nm,
        "material_density_kg_m3": sc.material_density_kg_m3,
        "youngs_modulus_gpa":     sc.youngs_modulus_gpa,
        "simulation_steps":       sc.simulation_steps,
        "check_collision":        sc.check_collision,
    }

    if mesh_url:
        payload["mesh_url"] = mesh_url
    if part_id:
        payload["part_id"] = part_id

    async with httpx.AsyncClient(timeout=_SIM_TIMEOUT) as client:
        if mesh_path and mesh_path.exists():
            with open(mesh_path, "rb") as f:
                files = {"mesh_file": (mesh_path.name, f, "model/stl")}
                r = await client.post(
                    f"{_SIM_URL}/simulate",
                    headers=headers,
                    files=files,
                    data={k: str(v) for k, v in payload.items()},
                )
        else:
            r = await client.post(
                f"{_SIM_URL}/simulate",
                headers=headers,
                json=payload,
            )

        r.raise_for_status()
        data = r.json()

    return _parse_result(data, sc.simulator)


async def get_simulation_status(job_id: str) -> SimulationResult:
    """Poll simulation status by job ID."""
    headers = {"X-API-Key": _SIM_KEY} if _SIM_KEY else {}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"{_SIM_URL}/simulate/{job_id}", headers=headers)
        r.raise_for_status()
        data = r.json()
    return _parse_result(data, data.get("simulator", _DEFAULT_SIM))


def _parse_result(data: dict, simulator: str) -> SimulationResult:
    """Parse the simulation API response into a SimulationResult."""
    # The nwo-simulation-api may return different field names
    # We handle the most common patterns gracefully
    status_str = data.get("status", "complete").lower()
    try:
        status = SimulationStatus(status_str)
    except ValueError:
        status = SimulationStatus.complete

    max_stress = data.get("max_stress_mpa") or data.get("max_stress") or data.get("stress_max_mpa")
    yield_str  = data.get("yield_strength_mpa") or data.get("material_yield_mpa") or 50.0  # PLA ~50 MPa

    safety_factor: float | None = None
    if max_stress and yield_str and max_stress > 0:
        safety_factor = round(float(yield_str) / float(max_stress), 2)

    # Pass if safety factor >= 1.5 and no critical stress points
    passed = bool(data.get("passed", True))
    if safety_factor is not None and safety_factor < 1.5:
        passed = False

    warnings = list(data.get("warnings", []))
    recommendations = list(data.get("recommendations", []))

    if safety_factor is not None and safety_factor < 2.0 and safety_factor >= 1.5:
        warnings.append(f"Safety factor {safety_factor:.1f}× is marginal. Consider increasing wall thickness.")
    if safety_factor is not None and safety_factor < 1.5:
        recommendations.append("Increase wall thickness or switch to PETG/ABS for higher strength.")
        recommendations.append("Consider adding gussets or ribs at stress concentration points.")

    stress_points = [
        StressPoint(
            location=p.get("location", [0, 0, 0]),
            stress_mpa=float(p.get("stress_mpa", 0)),
            is_critical=bool(p.get("is_critical", False)),
        )
        for p in data.get("stress_points", [])
    ]

    return SimulationResult(
        job_id=data.get("job_id", "unknown"),
        status=status,
        simulator=simulator,
        passed=passed,
        max_stress_mpa=float(max_stress) if max_stress else None,
        yield_strength_mpa=float(yield_str) if yield_str else None,
        safety_factor=safety_factor,
        max_displacement_mm=data.get("max_displacement_mm") or data.get("max_displacement"),
        natural_frequency_hz=data.get("natural_frequency_hz"),
        collision_detected=bool(data.get("collision_detected", False)),
        stress_points=stress_points,
        warnings=warnings,
        recommendations=recommendations,
        raw=data,
    )
