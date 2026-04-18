"""NWO Market Layer 6 CLI."""
from __future__ import annotations
import asyncio, os
import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.group()
def cli():
    """NWO Robotics Market Layer 6 — Identity, Simulation, Assembly AI, Token Economy."""


@cli.command()
@click.option("--host", default=None)
@click.option("--port", default=None, type=int)
@click.option("--reload", is_flag=True)
def serve(host, port, reload):
    """Start the Layer 6 market API."""
    import uvicorn
    _host = host or os.getenv("API_HOST", "0.0.0.0")
    _port = port or int(os.getenv("API_PORT", "8006"))
    console.print(f"\n[bold]NWO Market Layer 6[/bold] → http://{_host}:{_port}")
    console.print(f"  Docs    : http://{_host}:{_port}/docs")
    console.print(f"  Health  : http://{_host}:{_port}/v1/market/health\n")
    uvicorn.run("src.api.main:market_app", host=_host, port=_port, reload=reload)


@cli.command()
def health():
    """Check Layer 6 service health."""
    asyncio.run(_health())


async def _health():
    import httpx
    port = int(os.getenv("API_PORT", "8006"))
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.get(f"http://localhost:{port}/v1/market/health")
            data = r.json()
        except Exception as e:
            console.print(f"[red]Layer 6 unreachable: {e}[/red]"); return

    overall = "[green]OK[/green]" if data["status"] == "ok" else "[yellow]DEGRADED[/yellow]"
    console.print(f"\nMarket status: {overall}\n")

    t = Table(title="Services")
    t.add_column("Service"); t.add_column("Status"); t.add_column("Detail")
    for name, info in data.get("services", {}).items():
        ok = "[green]✓[/green]" if info.get("ok") else "[red]✗[/red]"
        detail = str(info.get("url") or info.get("latest_block") or info.get("model") or "")
        t.add_row(name, ok, detail)
    console.print(t)

    t2 = Table(title="Contracts (Base Mainnet)")
    t2.add_column("Contract"); t2.add_column("Address")
    for name, addr in data.get("contracts", {}).items():
        t2.add_row(name, addr or "not configured")
    console.print(t2)


@cli.command()
@click.argument("wallet")
@click.option("--serial", required=True, help="Robot serial number")
@click.option("--firmware", required=True, help="Firmware version")
@click.option("--api", default="http://localhost:8006")
def register_robot(wallet, serial, firmware, api):
    """Register a robot on Base Mainnet."""
    asyncio.run(_register(wallet, serial, firmware, api))


async def _register(wallet, serial, firmware, api_url):
    import httpx
    with console.status("Registering robot on Base Mainnet..."):
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(f"{api_url}/v1/market/identity/register-robot", json={
                "robot_wallet":     wallet,
                "serial_number":    serial,
                "firmware_version": firmware,
            })
    if r.status_code == 200:
        data = r.json()
        console.print(f"[green]✓[/green] Robot registered on Base Mainnet")
        console.print(f"  Token ID : {data.get('token_id')}")
        console.print(f"  TX Hash  : {data.get('tx_hash')}")
        console.print(f"  DID      : did:nwo:base:{data.get('token_id')}")
    else:
        console.print(f"[red]✗ Failed ({r.status_code}):[/red] {r.text}")


@cli.command()
@click.argument("part_id")
@click.option("--api", default="http://localhost:8006")
@click.option("--force", is_flag=True)
def assembly(part_id, api, force):
    """Generate assembly instructions for a part."""
    asyncio.run(_assembly(part_id, api, force))


async def _assembly(part_id, api_url, force):
    import httpx
    with console.status(f"Generating assembly instructions for {part_id}..."):
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(f"{api_url}/v1/market/assembly/instructions", json={
                "part_id": part_id, "force_regenerate": force
            })
    if r.status_code != 200:
        console.print(f"[red]✗ Failed:[/red] {r.text}"); return

    data = r.json()
    cached_note = " [dim](cached)[/dim]" if data.get("cached") else " [green](fresh)[/green]"
    console.print(f"\n[bold]{data['part_name']}[/bold]{cached_note}")
    console.print(f"  Difficulty : {data['difficulty']} | ~{data['estimated_time_min']} min")
    console.print(f"  Tools      : {', '.join(data.get('tools_required', []))}\n")

    for step in data.get("steps", []):
        console.print(f"[bold]Step {step['step']}: {step['title']}[/bold]")
        console.print(f"  {step['description']}")
        for w in step.get("warnings", []):
            console.print(f"  [yellow]⚠[/yellow]  {w}")

    console.print(f"\n[bold]Bill of Materials:[/bold]")
    t = Table()
    t.add_column("Item"); t.add_column("Qty"); t.add_column("Spec"); t.add_column("Source")
    for item in data.get("bill_of_materials", []):
        t.add_row(item["item"], str(item["quantity"]), item["specification"], item["source"])
    console.print(t)


if __name__ == "__main__":
    cli()
