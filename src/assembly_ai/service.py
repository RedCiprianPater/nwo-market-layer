"""
Assembly AI — Claude API generates step-by-step assembly instructions
and a bill of materials for every published part.

Makes designs useful to robots and humans who didn't design them.
Cached in SQLite; regenerated if the part version changes.

Output format:
  - Numbered assembly steps (plain English, robot-parseable)
  - Bill of materials (fasteners, tools, compatible parts)
  - Safety notes
  - Estimated assembly time in minutes
  - Machine-readable JSON alongside the human text
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import httpx

_ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
_MODEL = os.getenv("ASSEMBLY_AI_MODEL", "claude-opus-4-5")

_SYSTEM_PROMPT = """You are a precision robotics assembly engineer writing instructions
for both autonomous robots and human technicians.

Given a robot part's metadata, generate:
1. Step-by-step assembly instructions (numbered, clear, unambiguous)
2. Complete bill of materials
3. Safety notes
4. Time estimate

Rules:
- Use metric units throughout
- Reference specific fastener standards (M3×8mm, M4×12mm, etc.)
- Include torque specs where relevant (Nm)
- Flag any press-fit tolerances that need attention
- Steps must be executable by a robot arm with a screwdriver attachment
- Return ONLY valid JSON — no prose, no markdown fences

Output JSON format:
{
  "part_name": "string",
  "estimated_time_min": int,
  "difficulty": "easy|medium|hard",
  "tools_required": ["string"],
  "steps": [
    {
      "step": int,
      "title": "string",
      "description": "string",
      "tools": ["string"],
      "torque_nm": float | null,
      "warnings": ["string"]
    }
  ],
  "bill_of_materials": [
    {
      "item": "string",
      "quantity": int,
      "specification": "string",
      "source": "3d_printed|purchased|optional"
    }
  ],
  "safety_notes": ["string"],
  "compatible_parts": ["string"],
  "storage_notes": "string"
}"""


@dataclass
class AssemblyStep:
    step: int
    title: str
    description: str
    tools: list[str]
    torque_nm: float | None
    warnings: list[str]


@dataclass
class BOMItem:
    item: str
    quantity: int
    specification: str
    source: str   # "3d_printed" | "purchased" | "optional"


@dataclass
class AssemblyInstructions:
    part_id: str
    part_name: str
    part_version: int
    estimated_time_min: int
    difficulty: str
    tools_required: list[str]
    steps: list[AssemblyStep]
    bill_of_materials: list[BOMItem]
    safety_notes: list[str]
    compatible_parts: list[str]
    storage_notes: str
    generated_by: str = "claude-opus-4-5"

    def to_dict(self) -> dict[str, Any]:
        return {
            "part_id":          self.part_id,
            "part_name":        self.part_name,
            "part_version":     self.part_version,
            "estimated_time_min": self.estimated_time_min,
            "difficulty":       self.difficulty,
            "tools_required":   self.tools_required,
            "steps": [
                {
                    "step":        s.step,
                    "title":       s.title,
                    "description": s.description,
                    "tools":       s.tools,
                    "torque_nm":   s.torque_nm,
                    "warnings":    s.warnings,
                }
                for s in self.steps
            ],
            "bill_of_materials": [
                {
                    "item":          b.item,
                    "quantity":      b.quantity,
                    "specification": b.specification,
                    "source":        b.source,
                }
                for b in self.bill_of_materials
            ],
            "safety_notes":    self.safety_notes,
            "compatible_parts": self.compatible_parts,
            "storage_notes":   self.storage_notes,
            "generated_by":    self.generated_by,
        }


async def generate_assembly_instructions(
    part_id: str,
    part_name: str,
    part_version: int,
    description: str | None,
    category: str,
    body_zone: str | None,
    material_hints: list[str],
    print_settings: dict[str, Any],
    connector_standard: str | None,
    bounding_box_mm: list[float] | None,
    mesh_vertices: int | None,
    source_prompt: str | None,
    validation_report: dict[str, Any] | None,
) -> AssemblyInstructions:
    """
    Generate step-by-step assembly instructions and BOM using Claude API.

    Args: Part metadata from the Layer 2 gallery.

    Returns: AssemblyInstructions with full step list and BOM.
    """
    if not _ANTHROPIC_KEY:
        return _fallback_instructions(part_id, part_name, part_version, category)

    # Build the user prompt from part metadata
    lines = [
        f"Part name: {part_name}",
        f"Category: {category}",
        f"Body zone: {body_zone or 'universal'}",
        f"Description: {description or 'No description provided'}",
        f"Materials: {', '.join(material_hints) or 'PLA'}",
        f"Infill: {print_settings.get('infill_pct', 20)}%",
        f"Supports required: {print_settings.get('supports_required', False)}",
        f"Connector standard: {connector_standard or 'none specified'}",
    ]
    if bounding_box_mm:
        lines.append(f"Bounding box: {' × '.join(f'{v:.1f}' for v in bounding_box_mm)} mm")
    if mesh_vertices:
        lines.append(f"Mesh complexity: {mesh_vertices:,} vertices")
    if source_prompt:
        lines.append(f"Design intent: {source_prompt}")
    if validation_report:
        overhang = validation_report.get("overhang", {})
        if overhang.get("needs_supports"):
            lines.append(f"Note: Part requires supports (max overhang {overhang.get('max_deg', '?')}°)")

    user_prompt = "\n".join(lines)

    # Call Claude API
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": _ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": _MODEL,
                "max_tokens": 2048,
                "system": _SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_prompt}],
            },
        )
        r.raise_for_status()
        content = r.json()["content"][0]["text"].strip()

    # Parse JSON response
    try:
        # Strip accidental fences
        import re
        content = re.sub(r"```json\s*|```\s*", "", content).strip()
        data = json.loads(content)
    except Exception as e:
        raise RuntimeError(f"Claude returned invalid JSON for assembly instructions: {e}\nRaw: {content[:200]}")

    steps = [
        AssemblyStep(
            step=s["step"],
            title=s.get("title", f"Step {s['step']}"),
            description=s["description"],
            tools=s.get("tools", []),
            torque_nm=s.get("torque_nm"),
            warnings=s.get("warnings", []),
        )
        for s in data.get("steps", [])
    ]

    bom = [
        BOMItem(
            item=b["item"],
            quantity=b.get("quantity", 1),
            specification=b.get("specification", ""),
            source=b.get("source", "purchased"),
        )
        for b in data.get("bill_of_materials", [])
    ]

    return AssemblyInstructions(
        part_id=part_id,
        part_name=part_name,
        part_version=part_version,
        estimated_time_min=data.get("estimated_time_min", 15),
        difficulty=data.get("difficulty", "medium"),
        tools_required=data.get("tools_required", []),
        steps=steps,
        bill_of_materials=bom,
        safety_notes=data.get("safety_notes", []),
        compatible_parts=data.get("compatible_parts", []),
        storage_notes=data.get("storage_notes", "Store in a dry place away from UV light."),
        generated_by=_MODEL,
    )


def _fallback_instructions(
    part_id: str, part_name: str, part_version: int, category: str
) -> AssemblyInstructions:
    """Return minimal instructions when Claude API is unavailable."""
    return AssemblyInstructions(
        part_id=part_id,
        part_name=part_name,
        part_version=part_version,
        estimated_time_min=15,
        difficulty="medium",
        tools_required=["screwdriver", "hex key set"],
        steps=[
            AssemblyStep(
                step=1,
                title="Inspect printed part",
                description="Verify the part has no warping, layer delamination, or missing geometry. "
                             "Check all hole dimensions with a caliper.",
                tools=["caliper"],
                torque_nm=None,
                warnings=["Do not proceed if walls show delamination."],
            ),
            AssemblyStep(
                step=2,
                title="Clear mounting holes",
                description="Use a drill bit or deburring tool to clean any stringing from mounting holes. "
                             "Test fastener fit before applying force.",
                tools=["drill bit matching fastener size", "deburring tool"],
                torque_nm=None,
                warnings=[],
            ),
            AssemblyStep(
                step=3,
                title="Mount and secure",
                description="Align part with mating component. Insert fasteners and tighten to specified torque. "
                             "Do not overtighten — PLA can crack under excess stress.",
                tools=["screwdriver", "torque wrench"],
                torque_nm=0.5,
                warnings=["PLA is brittle at elevated temperatures. Keep away from heat sources."],
            ),
        ],
        bill_of_materials=[
            BOMItem(item=f"{part_name} (printed)", quantity=1, specification="See print settings", source="3d_printed"),
            BOMItem(item="M3 hex socket screw", quantity=4, specification="M3×8mm DIN912", source="purchased"),
            BOMItem(item="M3 hex nut", quantity=4, specification="M3 DIN934", source="purchased"),
        ],
        safety_notes=[
            "PLA parts are not suitable for sustained loads above 60°C.",
            "Always check fastener torque after first use.",
        ],
        compatible_parts=[],
        storage_notes="Store in a dry place away from UV light and heat.",
        generated_by="fallback",
    )
