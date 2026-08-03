from typing import Optional
import typer
from rich.console import Console
from rich.markdown import Markdown
from devwatch import __version__
from devwatch.crew.orchestrator import CodeReviewCrew

app = typer.Typer(
    name="DevWatch",
    help="Multi-Agent Code Review CLI System",
    add_completion=False,
)

console = Console()


def version_callback(value: bool):
    if value:
        console.print(f"[bold cyan]DevWatch v{__version__}[/bold cyan]")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-v",
        help="Show DevWatch version and exit.",
        callback=version_callback,
        is_eager=True,
    )
):
    """DevWatch 🛡️ Multi-Agent Code Review System"""
    pass


@app.command()
def review(
    path: str = typer.Argument(".", help="Path to codebase or file to review"),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help="Save markdown report to file path"
    ),
):
    """Run a multi-agent review on the specified codebase path."""
    console.print(f"[bold blue]🔍 Launching DevWatch Multi-Agent Review on:[/bold blue] {path}")

    crew = CodeReviewCrew()
    report = crew.run(path)

    md_content = report.summary
    console.print("\n")
    console.print(Markdown(md_content))

    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(md_content)
        console.print(f"\n[bold green]✅ Report saved to {output}[/bold green]")


if __name__ == "__main__":
    app()
