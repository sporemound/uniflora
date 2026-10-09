# ruff: noqa: E501
from __future__ import annotations

import argparse
import html
import textwrap
from pathlib import Path

# SVG copy remains legible beside the rendered layout when its source strings stay intact.

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "uniflora" / "content" / "assets"

POSITIONS = {
    0: {
        "title": "THE DRY NETWORK",
        "subtitle": "Name a permanent mark, discover need, repair circulation, and restore viability.",
        "objective": [
            "The first participant names the rootglass seed and chooses its irreversible fate.",
            "The group must then restore the damaged north-to-east water relation without making another region nonviable.",
        ],
        "phases": [
            (
                "RENEWAL",
                "Hypha opens the cycle",
                [
                    "Refresh action allowances",
                    "Apply existing scars and effects",
                    "Report the public state",
                ],
            ),
            (
                "ORIENTATION",
                "Discover and remember",
                [
                    "position · recall · orient",
                    "awaken · observe",
                    "Reveal need, capacity, and pathway facts",
                ],
            ),
            (
                "COORDINATION",
                "Build the repair relation",
                [
                    "connect · offer · request-support",
                    "Record donor, recipient, and shared work",
                    "One primary action per participant",
                ],
            ),
            (
                "VERIFICATION",
                "Check viability",
                [
                    "Compare available water and reserve floors",
                    "Account for the damaged path",
                    "Keep every participating region viable",
                ],
            ),
            (
                "PROPOSAL",
                "Commit a reconstruction",
                [
                    "act reconstruct",
                    "Name donor, recipient, amount, pathway",
                    "Include repair/accounting and maintenance",
                ],
            ),
            (
                "RESPONSE",
                "Others test the plan",
                [
                    "confirm or use the public stack",
                    "stack-react · kicker · trigger",
                    "The author cannot self-confirm",
                ],
            ),
            (
                "RESOLUTION",
                "Hypha applies state checks",
                [
                    "Transfer only after prerequisites hold",
                    "Success changes resources",
                    "Failure preserves discoveries and scars",
                ],
            ),
            (
                "REASSESSMENT",
                "Close and continue",
                [
                    "Record the maintained relation",
                    "Advance counters and triggers",
                    "Complete Position 0 or begin another cycle",
                ],
            ),
        ],
        "evidence": [
            "Northern usable capacity",
            "Eastern viability deficit",
            "Damaged circulation",
            "A repair contribution",
            "Shared participation",
        ],
        "proposal": [
            "donor and recipient",
            "water amount",
            "pathway",
            "repair or account",
            "maintenance condition",
        ],
        "success": [
            "3 distinct contributors",
            "non-author confirmation",
            "recipient viable",
            "donor reserve preserved",
        ],
    },
    2: {
        "title": "TRANSLATION",
        "subtitle": "One circulation, three instruments, three stages, and no disposable account.",
        "objective": [
            "Reconcile records made at source departure, boundary delivery, and later retention.",
            "Preserve provenance and minority warnings instead of forcing every accurate account into one total.",
        ],
        "phases": [
            (
                "RENEWAL",
                "Hypha opens the comparison",
                [
                    "Refresh contribution allowances",
                    "Preserve earlier annotations",
                    "Keep unresolved differences visible",
                ],
            ),
            (
                "ORIENTATION",
                "Inspect each record",
                [
                    "position · recall · map",
                    "observe records and references",
                    "Identify signatures, stages, and instruments",
                ],
            ),
            (
                "COMPARISON",
                "Place accounts together",
                [
                    "compare · clarify",
                    "Distinguish sent, delivered, retained",
                    "Do not treat chronology as contradiction",
                ],
            ),
            (
                "CLASSIFICATION",
                "Name the difference",
                [
                    "classify the relationship",
                    "different stages · scales · terminology",
                    "Leave unresolved differences unresolved",
                ],
            ),
            (
                "PUBLIC RECORD",
                "Relay without erasure",
                [
                    "relay-record · annotate",
                    "Restate each account accurately",
                    "Protect the minority report",
                ],
            ),
            (
                "PROPOSAL",
                "Build a concordance",
                [
                    "propose translation",
                    "Map all three records",
                    "Include shared summary and preserved difference",
                ],
            ),
            (
                "RESPONSE",
                "Independent confirmation",
                [
                    "Another participant checks provenance",
                    "Author cannot self-confirm",
                    "Reject summaries that collapse stages",
                ],
            ),
            (
                "REASSESSMENT",
                "Publish plural accuracy",
                [
                    "Record the concordance",
                    "Keep provenance attached",
                    "Complete Position 2 or compare again",
                ],
            ),
        ],
        "evidence": [
            "Source ledger",
            "Intake sensor",
            "Retention survey",
            "Archive glossary",
            "Provenance index",
            "Minority note",
        ],
        "proposal": [
            "three record IDs",
            "stage classification",
            "term mapping",
            "shared summary",
            "preserved difference",
        ],
        "success": [
            "3 distinct contributors",
            "non-author confirmation",
            "all stages preserved",
            "provenance remains public",
        ],
    },
    3: {
        "title": "THE PROVISION WORKS",
        "subtitle": "Test whether production provides reciprocally or exports its burdens to the settlement.",
        "objective": [
            "Inspect who receives goods and who carries water loss, heat, waste, risk, and maintenance.",
            "A valid charter must reduce the source of harm and make production publicly answerable.",
        ],
        "phases": [
            (
                "RENEWAL",
                "Hypha opens the audit",
                [
                    "Refresh allowances",
                    "Apply persistent burdens",
                    "Report Works and settlement state",
                ],
            ),
            (
                "ORIENTATION",
                "Inspect the system",
                [
                    "position · recall · map",
                    "works inspect",
                    "Trace intake, return, yard, well, and courts",
                ],
            ),
            (
                "AUDIT",
                "Compare claim and evidence",
                [
                    "works audit",
                    "Read benefit beside extraction",
                    "Keep worker and maintenance costs visible",
                ],
            ),
            (
                "SOURCE ACTION",
                "Change conditions",
                [
                    "works reduce · act mitigate",
                    "works contain",
                    "Cap throughput and protect workers",
                ],
            ),
            (
                "PROPOSAL",
                "Draft reciprocity",
                [
                    "propose reciprocity",
                    "Name benefit and local burden",
                    "Include reduction, disclosure, and obligations",
                ],
            ),
            (
                "RESPONSE",
                "Open public challenge",
                [
                    "stack-react · stack-resolve",
                    "reduce_source · protect_workers",
                    "audit_return · contain_substrate",
                ],
            ),
            (
                "RESOLUTION",
                "Test the charter",
                [
                    "Check evidence and burden transfer",
                    "Require maintenance and containment",
                    "Require a public shutdown condition",
                ],
            ),
            (
                "REASSESSMENT",
                "Record accountability",
                [
                    "Update public rights and duties",
                    "Preserve unresolved liabilities",
                    "Complete Position 3 or revise",
                ],
            ),
        ],
        "evidence": [
            "Local benefit",
            "Production intake",
            "Warm return",
            "Treatment labor",
            "Well recovery",
            "Heat Court burden",
        ],
        "proposal": [
            "public benefit",
            "local burden",
            "source reduction",
            "material disclosure",
            "worker protection",
            "shutdown condition",
        ],
        "success": [
            "3 distinct contributors",
            "non-author confirmation",
            "burdens not externalized",
            "public authority established",
        ],
    },
    4: {
        "title": "THE MAINTAINED REMEDIATION CYCLE",
        "subtitle": "Reduce first, separate flows, verify compatibility, maintain finite treatment, and contain residue.",
        "objective": [
            "Construct a finite remediation protocol whose evidence, capacity, maintenance, and containment are explicit.",
            "Treatment cannot substitute for reducing production at the source.",
        ],
        "phases": [
            (
                "RENEWAL",
                "Hypha updates the cycle",
                [
                    "Apply viability and saturation",
                    "Refresh maintenance windows",
                    "Report evidence and containment state",
                ],
            ),
            (
                "INSPECTION",
                "Establish prerequisites",
                [
                    "inspect Works, return, and culture archive",
                    "Confirm discharge and culture identity",
                    "Do not infer safety from appearance",
                ],
            ),
            (
                "SEPARATION",
                "Keep flows distinct",
                [
                    "works separate",
                    "Route clean and contaminated flows",
                    "Prevent mixed-flow treatment",
                ],
            ),
            (
                "MAINTENANCE",
                "Prepare finite treatment",
                [
                    "sustain or inoculate",
                    "slow flow and preserve contact time",
                    "rest or replace saturated substrate",
                ],
            ),
            (
                "EVIDENCE",
                "Measure performance",
                [
                    "sample upstream and downstream",
                    "works audit",
                    "Compare evidence, not color alone",
                ],
            ),
            (
                "PROPOSAL",
                "Write the protocol",
                [
                    "propose remediation",
                    "Include reduction, compatibility, limits",
                    "Name monitoring, custody, and shutdown",
                ],
            ),
            (
                "RESPONSE",
                "Challenge weak links",
                [
                    "stack-react · stack-resolve",
                    "object evidence or compatibility",
                    "protect workers and preserve archive",
                ],
            ),
            (
                "REASSESSMENT",
                "Maintain or stop",
                [
                    "Update viability and saturation",
                    "Contain spent substrate",
                    "Complete Position 4 or reopen maintenance",
                ],
            ),
        ],
        "evidence": [
            "Characterized discharge",
            "Compatible culture",
            "Up/downstream samples",
            "Bed viability",
            "Saturation",
            "Containment custody",
        ],
        "proposal": [
            "source reduction",
            "flow and moisture",
            "culture and substrate",
            "evidence threshold",
            "saturation limit",
            "shutdown condition",
        ],
        "success": [
            "3 distinct contributors",
            "non-author confirmation",
            "capacity remains finite",
            "spent material contained",
        ],
    },
    5: {
        "title": "MEMORY",
        "subtitle": "Correct the archive without deleting the assurances, revisions, failures, or unresolved conflict.",
        "objective": [
            "Reconstruct the versioned history of a failed treatment and the burden that re-entered circulation.",
            "Correction must preserve who knew what, when they knew it, and what remained uncertain.",
        ],
        "phases": [
            (
                "RENEWAL",
                "Hypha opens the archive",
                [
                    "Preserve all prior versions",
                    "Refresh documentation allowances",
                    "Keep unresolved conflicts visible",
                ],
            ),
            (
                "INSPECTION",
                "Read records and traces",
                [
                    "works inspect",
                    "Locate claim, revision, evidence, omission",
                    "Trace affected observations",
                ],
            ),
            (
                "AUDIT",
                "Test records against evidence",
                [
                    "works audit",
                    "Compare claims with samples and failures",
                    "Do not overwrite earlier language",
                ],
            ),
            (
                "VERSIONING",
                "Create public history",
                [
                    "works document",
                    "Record claim, revision, failure, correction",
                    "Create at least two versioned records",
                ],
            ),
            (
                "CUSTODY",
                "Protect material evidence",
                [
                    "works contain",
                    "Keep spent substrate out of food soil",
                    "Attach handling requirements",
                ],
            ),
            (
                "PROPOSAL",
                "Propose public memory",
                [
                    "propose memory",
                    "Name evidence, uncertainty, correction",
                    "Preserve unresolved conflict",
                ],
            ),
            (
                "RESPONSE",
                "Challenge the archive",
                [
                    "stack-react · kicker",
                    "object evidence · preserve archive",
                    "Add disclosure or monitoring duties",
                ],
            ),
            (
                "REASSESSMENT",
                "Publish without erasure",
                [
                    "Confirm version order and custody",
                    "Retain failed and corrected accounts",
                    "Complete Position 5 or document more",
                ],
            ),
        ],
        "evidence": [
            "Original assurance",
            "Later revision",
            "Physical measurement",
            "Omitted failure",
            "Affected observation",
            "Handling record",
        ],
        "proposal": [
            "original and revision",
            "physical evidence",
            "uncertainty",
            "correction",
            "unresolved conflict",
            "handling requirement",
        ],
        "success": [
            "3 distinct contributors",
            "non-author confirmation",
            "versions remain accessible",
            "failure and custody preserved",
        ],
    },
    6: {
        "title": "RECONSTRUCTION",
        "subtitle": "Make production answerable to public need, ecological limits, livelihoods, water, waste, and memory.",
        "objective": [
            "Choose a viable future for the Works: constrain, retrofit, distribute, operate seasonally, reclaim, or transfer ownership.",
            "Every model must reduce throughput before expanding remediation and preserve public authority to stop it.",
        ],
        "phases": [
            (
                "RENEWAL",
                "Hypha presents inherited state",
                [
                    "Carry forward burdens and records",
                    "Refresh final-cycle allowances",
                    "Report water, work, waste, and governance",
                ],
            ),
            (
                "ORIENTATION",
                "Inspect the whole relation",
                [
                    "position · recall · orient",
                    "works inspect · sample · audit",
                    "Review evidence from every prior position",
                ],
            ),
            (
                "REDUCTION",
                "Lower harmful scale",
                [
                    "works reduce",
                    "Reduce throughput, water draw, or waste",
                    "Refuse unnecessary production first",
                ],
            ),
            (
                "REDESIGN",
                "Choose a public model",
                [
                    "works redesign · separate · contain",
                    "sustain public systems",
                    "mitigate worker and transition burdens",
                ],
            ),
            (
                "DOCUMENTATION",
                "Bind memory to governance",
                [
                    "works document",
                    "Preserve failures and obligations",
                    "Name reassessment and shutdown authority",
                ],
            ),
            (
                "PROPOSAL",
                "Propose reconstruction",
                [
                    "Lower revised output and water cap",
                    "Protect work or fund transition",
                    "Include clean flow, custody, and monitoring",
                ],
            ),
            (
                "RESPONSE",
                "Publicly contest the model",
                [
                    "stack-react · stack-resolve · kicker",
                    "reduce_source · protect_workers",
                    "cap_throughput · preserve_archive",
                ],
            ),
            (
                "RESOLUTION",
                "Ratify or return",
                [
                    "Check all ecological and social duties",
                    "Require public governance and stop rights",
                    "Complete the game or revise the model",
                ],
            ),
        ],
        "evidence": [
            "Public need",
            "Current output",
            "Water and waste limits",
            "Worker transition",
            "Historical record",
            "Governance authority",
        ],
        "proposal": [
            "production model",
            "lower output",
            "water cap",
            "worker transition",
            "ownership/governance",
            "monitoring and shutdown",
        ],
        "success": [
            "4 distinct contributors",
            "non-author confirmation",
            "source reduction first",
            "public reassessment and stop rights",
        ],
    },
}

COLORS = ["#96c95d", "#75bd66", "#53c6d6", "#6f95ee", "#bd76e0", "#ec9c35", "#ed6c58", "#ddca43"]


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def text_block(x: int, y: int, lines: list[str], css: str, *, width: int, gap: int = 27) -> str:
    output: list[str] = []
    current_y = y
    for source in lines:
        wrapped = textwrap.wrap(source, width=width, break_long_words=False) or [""]
        for line in wrapped:
            output.append(f'<text x="{x}" y="{current_y}" class="{css}">{esc(line)}</text>')
            current_y += gap
        current_y += 7
    return "\n".join(output)


def list_block(x: int, y: int, lines: list[str], *, width: int = 48, gap: int = 27) -> str:
    expanded: list[str] = []
    for source in lines:
        wrapped = textwrap.wrap(source, width=width, break_long_words=False) or [""]
        for index, line in enumerate(wrapped):
            expanded.append(("• " if index == 0 else "  ") + line)
    return "\n".join(
        f'<text x="{x}" y="{y + index * gap}" class="body">{esc(line)}</text>'
        for index, line in enumerate(expanded)
    )


def render(position: int, data: dict[str, object]) -> str:
    phases = data["phases"]
    assert isinstance(phases, list)
    phase_parts: list[str] = []
    start_y = 235
    panel_height = 215
    for index, phase in enumerate(phases):
        name, lead, details = phase
        y = start_y + index * 240
        color = COLORS[index]
        phase_parts.extend(
            [
                f'<rect x="415" y="{y}" width="770" height="{panel_height}" class="phase" stroke="{color}"/>',
                f'<text x="445" y="{y + 43}" class="phase-title" fill="{color}">{index + 1}. {esc(name)}</text>',
                f'<text x="445" y="{y + 79}" class="lead">{esc(lead)}</text>',
                list_block(465, y + 116, list(details), width=59, gap=27),
            ]
        )
        if index < len(phases) - 1:
            phase_parts.append(f'<path d="M800 {y + panel_height} V{y + 237}" class="arrow"/>')

    objective = list(data["objective"])
    evidence = list(data["evidence"])
    proposal = list(data["proposal"])
    success = list(data["success"])
    command_surfaces = ["/interior position"]
    if position in {1, 2, 3, 4, 5}:
        command_surfaces.append("/interior map")
    command_surfaces.extend(
        [
            "/interior chart",
            "/interior recall",
            "/interior accessibility",
            "Discord exposes fields for position-specific commands",
        ]
    )
    title_size = 40 if len(str(data["title"])) > 30 else 55
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="2200" viewBox="0 0 1600 2200" role="img" aria-labelledby="title desc">
  <title id="title">Position {position} cycle flow chart: {esc(str(data["title"]))}</title>
  <desc id="desc">A public flow chart showing asynchronous workflow areas, interleavable preparation, required evidence, proposal contents, and completion checks for Position {position}.</desc>
  <defs>
    <radialGradient id="bg" cx="50%" cy="30%" r="80%"><stop offset="0" stop-color="#0b251d"/><stop offset="1" stop-color="#03110d"/></radialGradient>
    <marker id="arrowhead" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="#ddd6b5"/></marker>
    <style>
      text{{font-family:'Segoe UI',Arial,sans-serif;fill:#dedcc9}}
      .title{{font-size:55px;font-weight:800;letter-spacing:4px;fill:#e5d9ae}}
      .subtitle{{font-size:24px;fill:#bdbb95}}
      .phase{{fill:#0c2019;stroke-width:2.5;rx:18}}
      .phase-title{{font-size:27px;font-weight:800}}
      .lead{{font-size:22px;font-weight:650;fill:#f0ead1}}
      .body{{font-size:19px}}
      .side-title{{font-size:23px;font-weight:800;fill:#efbb3e}}
      .side{{font-size:18px}}
      .panel{{fill:#091a15;stroke:#a99865;stroke-width:2;rx:16}}
      .note{{fill:#0a1d17;stroke:#5dc5d2;stroke-width:2;stroke-dasharray:7 5;rx:14}}
      .arrow{{fill:none;stroke:#ddd6b5;stroke-width:3;marker-end:url(#arrowhead)}}
    </style>
  </defs>
  <rect width="1600" height="2200" fill="url(#bg)"/>
  <text id="svg-title" x="800" y="68" text-anchor="middle" class="title" style="font-size:{title_size}px">POSITION {position} — {esc(str(data["title"]))}</text>
  <text x="800" y="110" text-anchor="middle" class="subtitle">{esc(str(data["subtitle"]))}</text>
  <rect x="55" y="140" width="1490" height="64" class="panel" stroke="#d49b27"/>
  <text x="800" y="180" text-anchor="middle" class="lead">PREPARATION MAY RETURN TO EARLIER WORK · ONLY RESPONSE PAUSES ORDINARY ACTIONS</text>

  <rect x="45" y="235" width="335" height="475" class="panel"/>
  <text x="70" y="278" class="side-title">POSITION OBJECTIVE</text>
  {text_block(70, 320, objective, "side", width=34, gap=26)}
  <text x="70" y="570" class="side-title">SCALES OF PLAY</text>
  <text x="70" y="610" class="side">Position = the full chapter</text>
  <text x="70" y="645" class="side">Cycle = one collective attempt</text>
  <text x="70" y="680" class="side">Turn = one accepted primary action</text>

  <rect x="45" y="740" width="335" height="420" class="panel"/>
  <text x="70" y="783" class="side-title">PUBLIC RULES</text>
  {list_block(70, 825, ["Preparation activities may interleave", "Evidence prerequisites still apply", "One primary action per participant per cycle", "A counted contributor may assemble the proposal", "A proposal author cannot self-confirm", "Failure preserves confirmed discoveries"], width=31, gap=28)}

  <rect x="45" y="1190" width="335" height="380" class="panel"/>
  <text x="70" y="1233" class="side-title">COMMAND SURFACES</text>
  {list_block(70, 1275, command_surfaces, width=31, gap=28)}

  {"".join(phase_parts)}

  <rect x="1220" y="235" width="330" height="410" class="note"/>
  <text x="1245" y="278" class="side-title">EVIDENCE TO MAKE PUBLIC</text>
  {list_block(1245, 320, evidence, width=29, gap=28)}

  <rect x="1220" y="690" width="330" height="460" class="note" stroke="#bd76e0"/>
  <text x="1245" y="733" class="side-title">PROPOSAL MUST INCLUDE</text>
  {list_block(1245, 775, proposal, width=29, gap=28)}

  <rect x="1220" y="1195" width="330" height="380" class="note" stroke="#ed6c58"/>
  <text x="1245" y="1238" class="side-title">COMPLETION CHECKS</text>
  {list_block(1245, 1280, success, width=29, gap=28)}

  <rect x="1220" y="1620" width="330" height="300" class="note" stroke="#ddca43"/>
  <text x="1245" y="1663" class="side-title">AT REASSESSMENT</text>
  {list_block(1245, 1705, ["Apply accepted changes", "Advance persistent counters", "Retain burdens and disagreements", "Open another cycle unless the position is complete"], width=29, gap=28)}

  <rect x="60" y="2140" width="1480" height="1" fill="#a99865"/>
  <text x="80" y="2180" class="side" fill="#efbb3e">PUBLIC RECORD: confirmed facts, contributions, scars, and unresolved burdens persist.</text>
  <text x="1520" y="2180" text-anchor="end" class="side" fill="#5dc5d2">THE MISSING INTERIOR · POSITION {position}</text>
</svg>
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("positions", nargs="*", type=int, default=sorted(POSITIONS))
    parser.add_argument(
        "--png",
        action="store_true",
        help="also refresh packaged PNGs with resvg_py",
    )
    args = parser.parse_args()
    ASSETS.mkdir(parents=True, exist_ok=True)
    for position in args.positions:
        if position not in POSITIONS:
            raise SystemExit(f"No generated chart definition for Position {position}")
        destination = ASSETS / f"position_{position}_cycle_flow_chart.svg"
        svg = render(position, POSITIONS[position])
        destination.write_text(svg, encoding="utf-8")
        print(destination.relative_to(ROOT))
        if args.png:
            import resvg_py

            png_destination = destination.with_suffix(".png")
            png_destination.write_bytes(resvg_py.svg_to_bytes(svg_string=svg))
            print(png_destination.relative_to(ROOT))


if __name__ == "__main__":
    main()
