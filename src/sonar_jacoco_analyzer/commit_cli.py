"""
Interactive CLI for AI-powered commit message generation.
"""

import atexit
import glob
import os
import readline
import sys
from typing import List, Optional

# History file for input persistence (shared with main CLI)
HISTORY_FILE = os.path.expanduser("~/.sonar_jacoco_history")
HISTORY_MAX_LENGTH = 500
_history_initialized = False

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.text import Text
from rich.syntax import Syntax
from rich.markdown import Markdown

from .commit_config import CommitConfig, ConfigurationError
from .git_operations import (
    GitOperations,
    NotAGitRepositoryError,
    NoStagedChangesError,
    StagedChanges,
    ChangeMetrics,
)
from .github_client import (
    GitHubClient,
    GitHubClientError,
    AuthenticationError as GitHubAuthError,
    RateLimitError as GitHubRateLimitError,
    RepositoryInfo as GitHubRepoInfo,
    BranchInfo as GitHubBranchInfo,
    CommitInfo as GitHubCommitInfo,
)
from .gitlab_client import (
    GitLabClient,
    GitLabClientError,
    AuthenticationError as GitLabAuthError,
    RateLimitError as GitLabRateLimitError,
    RepositoryInfo as GitLabRepoInfo,
    BranchInfo as GitLabBranchInfo,
    CommitInfo as GitLabCommitInfo,
)
from .commit_generator import (
    CommitGenerator,
    GeneratedCommit,
    CommitGeneratorError,
)
from .commit_splitter import (
    CommitSplitter,
    SplitProposal,
    SplitGroup,
)
from .conventional_commit import CommitType

console = Console()


def setup_input_history():
    """
    Initialize readline input history.

    Loads history from file and configures readline for persistent history.
    This allows users to use up/down arrows to navigate through previous inputs.
    """
    global _history_initialized
    if _history_initialized:
        return
    _history_initialized = True

    # Configure history settings
    readline.set_history_length(HISTORY_MAX_LENGTH)

    # Load existing history file if it exists
    try:
        if os.path.exists(HISTORY_FILE):
            readline.read_history_file(HISTORY_FILE)
    except (IOError, OSError, PermissionError):
        # Silently ignore history load errors
        pass

    # Register save function to run at exit
    atexit.register(save_input_history)


def save_input_history():
    """
    Save readline input history to file.

    Called automatically at exit via atexit, but can also be called manually.
    """
    try:
        # Ensure parent directory exists
        history_dir = os.path.dirname(HISTORY_FILE)
        if history_dir and not os.path.exists(history_dir):
            os.makedirs(history_dir, exist_ok=True)

        readline.write_history_file(HISTORY_FILE)
    except (IOError, OSError, PermissionError):
        # Silently ignore history save errors
        pass


def print_banner():
    """Print the application banner."""
    console.print()
    console.print(
        Panel(
            "[bold]AI-POWERED COMMIT MESSAGE GENERATOR[/bold]\n"
            "[dim]Generate conventional commit messages with AI assistance[/dim]",
            border_style="cyan",
            padding=(1, 4),
        )
    )
    console.print()


def show_error(message: str, hint: Optional[str] = None):
    """Display an error message."""
    console.print(f"[red]Error:[/red] {message}")
    if hint:
        console.print(f"[dim]Hint: {hint}[/dim]")


def show_success(message: str):
    """Display a success message."""
    console.print(f"[green]{message}[/green]")


def show_warning(message: str):
    """Display a warning message."""
    console.print(f"[yellow]Warning:[/yellow] {message}")


def expand_path(path: str) -> str:
    """
    Expand environment variables and user home in path.

    Args:
        path: Path string that may contain $VAR or ~ notation.

    Returns:
        Expanded absolute path.
    """
    # Expand environment variables like $HOME, $USER, etc.
    expanded = os.path.expandvars(path)
    # Expand ~ to user home directory
    expanded = os.path.expanduser(expanded)
    # Convert to absolute path
    if expanded:
        expanded = os.path.abspath(expanded)
    return expanded


def path_completer(text: str, state: int) -> Optional[str]:
    """
    Tab completion function for file paths.

    Args:
        text: Current text being completed.
        state: State index for multiple completions.

    Returns:
        Next completion match or None.
    """
    # Expand variables first
    expanded = os.path.expandvars(text)
    expanded = os.path.expanduser(expanded)

    # Handle empty input
    if not expanded:
        expanded = "./"

    # Add wildcard for glob matching
    if os.path.isdir(expanded):
        pattern = os.path.join(expanded, "*")
    else:
        pattern = expanded + "*"

    # Get matches
    matches = glob.glob(pattern)

    # Add trailing slash to directories
    matches = [m + "/" if os.path.isdir(m) else m for m in matches]

    # Sort matches
    matches = sorted(matches)

    try:
        return matches[state]
    except IndexError:
        return None


def setup_path_completion():
    """Configure readline for path tab completion."""
    # Set the completer function
    readline.set_completer(path_completer)

    # Configure completion settings
    readline.set_completer_delims(" \t\n;")

    # Enable tab completion
    # Use different binding for different platforms
    if sys.platform == "darwin":
        readline.parse_and_bind("bind ^I rl_complete")
    else:
        readline.parse_and_bind("tab: complete")


def prompt_for_path(prompt_text: str, default: str = ".") -> str:
    """
    Prompt user for a path with tab completion support.

    Args:
        prompt_text: Text to display in the prompt.
        default: Default value if user presses Enter.

    Returns:
        Expanded path string.
    """
    # Setup tab completion
    setup_path_completion()

    console.print(f"[bold]{prompt_text}[/bold]")
    console.print("[dim]Supports: Tab completion, ~, $HOME, $USER, etc.[/dim]")
    console.print("[dim]Use ↑/↓ arrow keys to navigate input history.[/dim]")
    console.print(f"[dim]Press Enter for current directory ({os.getcwd()})[/dim]")
    console.print()

    try:
        # Use raw input to support readline
        user_input = input(f"Path [{default}]: ").strip()

        if not user_input:
            user_input = default

        # Expand the path
        expanded = expand_path(user_input)

        return expanded

    except (EOFError, KeyboardInterrupt):
        console.print()
        return expand_path(default)
    finally:
        # Reset completer to avoid affecting other prompts
        readline.set_completer(None)


def show_main_menu() -> str:
    """
    Display the main menu and get user choice.

    Returns:
        User's choice: 'local', 'github', or 'gitlab'
    """
    console.print("[bold]Select repository source:[/bold]")
    console.print()
    console.print(
        "    [green][1][/green] Local Repository "
        "[dim](commit staged changes)[/dim]"
    )
    console.print(
        "    [green][2][/green] GitHub Repository "
        "[dim](analyze remote commits)[/dim]"
    )
    console.print(
        "    [green][3][/green] GitLab Repository "
        "[dim](analyze remote commits)[/dim]"
    )
    console.print()

    try:
        choice = Prompt.ask(
            "[bold]Enter choice[/bold]",
            choices=["1", "2", "3"],
            show_choices=False,
        )
        if choice == "1":
            return "local"
        elif choice == "2":
            return "github"
        else:
            return "gitlab"
    except (EOFError, KeyboardInterrupt):
        console.print("\n[dim]Cancelled.[/dim]")
        sys.exit(0)


def select_github_repository(client: GitHubClient) -> Optional[RepositoryInfo]:
    """
    Interactive repository selection from GitHub.

    Args:
        client: GitHub client instance.

    Returns:
        Selected RepositoryInfo or None if cancelled.
    """
    with console.status("[cyan]Fetching repositories from GitHub...[/cyan]"):
        try:
            repos = client.list_repositories()
        except GitHubClientError as e:
            show_error(str(e))
            return None

    if not repos:
        show_warning("No repositories found.")
        return None

    console.print(f"[green]Found {len(repos)} repositories.[/green]")
    console.print()

    # Display repository table
    table = Table(title="Your Repositories", box=None, padding=(0, 1))
    table.add_column("#", justify="right", width=4, style="dim")
    table.add_column("Repository", width=40)
    table.add_column("Language", width=12)
    table.add_column("Stars", justify="right", width=6)
    table.add_column("Updated", width=12)

    for i, repo in enumerate(repos[:30], 1):
        visibility = "[dim](private)[/dim]" if repo.private else ""
        updated = repo.updated_at.strftime("%Y-%m-%d") if repo.updated_at else "N/A"
        table.add_row(
            str(i),
            f"{repo.full_name} {visibility}",
            repo.language or "-",
            str(repo.stars),
            updated,
        )

    console.print(table)

    if len(repos) > 30:
        console.print(f"[dim]Showing first 30 of {len(repos)} repositories.[/dim]")

    console.print()

    try:
        # Allow search or selection
        choice = Prompt.ask(
            "[bold]Enter number to select, or type to search[/bold]"
        )

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(repos):
                return repos[idx]
            show_error("Invalid selection.")
            return None
        else:
            # Search by name
            matches = [r for r in repos if choice.lower() in r.full_name.lower()]
            if len(matches) == 1:
                return matches[0]
            elif len(matches) > 1:
                console.print(f"[yellow]Multiple matches found:[/yellow]")
                for i, repo in enumerate(matches[:10], 1):
                    console.print(f"  [{i}] {repo.full_name}")
                sub_choice = Prompt.ask("Select number", default="1")
                idx = int(sub_choice) - 1
                if 0 <= idx < len(matches):
                    return matches[idx]
            else:
                show_warning("No matching repositories found.")
                return None

    except (EOFError, KeyboardInterrupt):
        return None


def select_branch(client: GitHubClient, repo_name: str) -> Optional[BranchInfo]:
    """
    Interactive branch selection.

    Args:
        client: GitHub client instance.
        repo_name: Full repository name.

    Returns:
        Selected BranchInfo or None if cancelled.
    """
    with console.status("[cyan]Fetching branches...[/cyan]"):
        try:
            branches = client.list_branches(repo_name)
        except GitHubClientError as e:
            show_error(str(e))
            return None

    if not branches:
        show_warning("No branches found.")
        return None

    console.print()
    console.print("[bold]Select branch:[/bold]")
    console.print()

    for i, branch in enumerate(branches[:20], 1):
        indicators = []
        if branch.is_default:
            indicators.append("[green]default[/green]")
        if branch.is_protected:
            indicators.append("[yellow]protected[/yellow]")
        indicator_str = f" ({', '.join(indicators)})" if indicators else ""
        console.print(f"    [green][{i}][/green] {branch.name}{indicator_str}")

    console.print()

    try:
        choice = Prompt.ask(
            "[bold]Enter choice[/bold]",
            default="1",
        )
        idx = int(choice) - 1
        if 0 <= idx < len(branches):
            return branches[idx]
        show_error("Invalid selection.")
        return None
    except (EOFError, KeyboardInterrupt, ValueError):
        return None


def select_commits(
    client: GitHubClient, repo_name: str, branch_name: str
) -> List[CommitInfo]:
    """
    Interactive commit selection (multi-select).

    Args:
        client: GitHub client instance.
        repo_name: Full repository name.
        branch_name: Branch name.

    Returns:
        List of selected CommitInfo objects.
    """
    with console.status("[cyan]Fetching commits...[/cyan]"):
        try:
            commits = client.list_commits(repo_name, branch_name, limit=50)
        except GitHubClientError as e:
            show_error(str(e))
            return []

    if not commits:
        show_warning("No commits found.")
        return []

    console.print()
    console.print("[bold]Select commits to analyze:[/bold]")
    console.print("[dim]Enter numbers separated by spaces, or 'all' for all commits[/dim]")
    console.print()

    table = Table(box=None, padding=(0, 1))
    table.add_column("#", justify="right", width=3, style="dim")
    table.add_column("SHA", width=8, style="yellow")
    table.add_column("Message", width=50)
    table.add_column("Author", width=15)
    table.add_column("Date", width=12)

    for i, commit in enumerate(commits[:30], 1):
        message = commit.message.split("\n")[0][:48]
        date = commit.date.strftime("%Y-%m-%d") if commit.date else "N/A"
        table.add_row(
            str(i),
            commit.short_sha,
            message,
            commit.author_name[:14],
            date,
        )

    console.print(table)
    console.print()

    try:
        choice = Prompt.ask("[bold]Enter selection[/bold]", default="1")

        if choice.lower() == "all":
            return commits[:30]

        # Parse selection
        selected = []
        for part in choice.split():
            if "-" in part:
                # Range selection (e.g., "1-5")
                start, end = part.split("-")
                for i in range(int(start), int(end) + 1):
                    if 1 <= i <= len(commits):
                        selected.append(commits[i - 1])
            else:
                idx = int(part) - 1
                if 0 <= idx < len(commits):
                    selected.append(commits[idx])

        return selected

    except (EOFError, KeyboardInterrupt, ValueError):
        return []


def display_staged_changes(staged: StagedChanges, metrics: ChangeMetrics):
    """Display staged changes summary."""
    console.print()
    console.print("[bold]Staged Changes Summary[/bold]")
    console.print()

    # Summary stats
    stats_table = Table(show_header=False, box=None, padding=(0, 2))
    stats_table.add_column("Metric", style="blue")
    stats_table.add_column("Value", style="bold")

    stats_table.add_row("Files Changed", str(metrics.total_files))
    stats_table.add_row(
        "Lines",
        f"[green]+{staged.total_additions}[/green] [red]-{staged.total_deletions}[/red]",
    )
    stats_table.add_row("Directories", str(metrics.directories_affected))
    stats_table.add_row("Complexity Score", str(metrics.complexity_score))

    console.print(stats_table)
    console.print()

    # File list
    console.print("[bold]Changed Files:[/bold]")
    for f in staged.files[:15]:
        status_colors = {"A": "green", "M": "yellow", "D": "red", "R": "blue"}
        status_names = {"A": "added", "M": "modified", "D": "deleted", "R": "renamed"}
        color = status_colors.get(f.status, "white")
        status = status_names.get(f.status, f.status)
        console.print(
            f"    [{color}]{status:10}[/{color}] {f.file_path} "
            f"[dim](+{f.additions} -{f.deletions})[/dim]"
        )

    if len(staged.files) > 15:
        console.print(f"    [dim]... and {len(staged.files) - 15} more files[/dim]")

    console.print()


def display_split_proposal(proposal: SplitProposal) -> bool:
    """
    Display split proposal and get user decision.

    Args:
        proposal: Split proposal to display.

    Returns:
        True if user wants to split, False otherwise.
    """
    console.print()
    console.print(Panel(
        "[bold yellow]Large Change Detected[/bold yellow]\n\n"
        f"{proposal.rationale}",
        border_style="yellow",
    ))
    console.print()

    console.print(f"[bold]Proposed Split ({len(proposal.groups)} commits):[/bold]")
    console.print()

    table = Table(box=None, padding=(0, 1))
    table.add_column("#", justify="right", width=3, style="dim")
    table.add_column("Category", width=15)
    table.add_column("Files", justify="right", width=6)
    table.add_column("Lines", justify="right", width=10)
    table.add_column("Type", width=10)
    table.add_column("Description", width=35)

    for i, group in enumerate(proposal.groups, 1):
        lines = f"+{group.total_additions} -{group.total_deletions}"
        table.add_row(
            str(i),
            group.category.value,
            str(group.file_count),
            lines,
            group.suggested_type.type_name,
            group.description[:33],
        )

    console.print(table)
    console.print()

    try:
        return Confirm.ask("Split into multiple commits?", default=True)
    except (EOFError, KeyboardInterrupt):
        return False


def display_commit_preview(commit: GeneratedCommit, diff_summary: str):
    """Display commit message preview."""
    console.print()

    # Type badge
    type_colors = {
        "feat": "green",
        "fix": "red",
        "docs": "blue",
        "style": "magenta",
        "refactor": "yellow",
        "test": "cyan",
        "chore": "dim",
        "perf": "green",
        "ci": "blue",
        "build": "yellow",
        "revert": "red",
    }
    color = type_colors.get(commit.type.type_name, "white")

    # Display commit message in panel
    message_display = Syntax(
        commit.formatted_message,
        "text",
        theme="monokai",
        word_wrap=True,
    )

    console.print(Panel(
        message_display,
        title=f"[{color}]{commit.type.type_name.upper()}[/{color}] Commit Message",
        border_style=color,
        padding=(1, 2),
    ))

    console.print()
    console.print(f"[dim]{diff_summary}[/dim]")
    console.print()


def request_user_approval() -> str:
    """
    Request user approval for commit.

    Returns:
        User's choice: 'approve', 'edit', 'regenerate', or 'cancel'
    """
    console.print("[bold]Options:[/bold]")
    console.print("    [green][A]pprove[/green]    - Create commit with this message")
    console.print("    [yellow][E]dit[/yellow]       - Modify the message manually")
    console.print("    [blue][R]egenerate[/blue] - Generate a new message")
    console.print("    [red][C]ancel[/red]     - Abort without committing")
    console.print()

    try:
        choice = Prompt.ask(
            "[bold]Your choice[/bold]",
            choices=["a", "e", "r", "c", "approve", "edit", "regenerate", "cancel"],
            show_choices=False,
        ).lower()

        choice_map = {
            "a": "approve",
            "e": "edit",
            "r": "regenerate",
            "c": "cancel",
        }
        return choice_map.get(choice, choice)

    except (EOFError, KeyboardInterrupt):
        return "cancel"


def edit_commit_message(original: str) -> str:
    """
    Allow user to edit commit message.

    Args:
        original: Original commit message.

    Returns:
        Edited commit message.
    """
    console.print()
    console.print("[bold]Edit the commit message:[/bold]")
    console.print("[dim]Enter new message (blank line + 'END' to finish):[/dim]")
    console.print()

    # Show original for reference
    console.print("[dim]Original:[/dim]")
    for line in original.split("\n"):
        console.print(f"[dim]> {line}[/dim]")
    console.print()

    lines = []
    try:
        while True:
            line = input()
            if line.strip().upper() == "END":
                break
            lines.append(line)
    except (EOFError, KeyboardInterrupt):
        return original

    if lines:
        return "\n".join(lines)
    return original


def display_commit_result(git_ops: GitOperations, sha: str):
    """Display the result of a successful commit."""
    console.print()
    show_success("Commit created successfully!")
    console.print()

    # Show commit log
    log_output = git_ops.show_last_commit()
    console.print(Panel(
        log_output,
        title="[green]Commit Details[/green]",
        border_style="green",
    ))
    console.print()


def run_local_workflow(config: CommitConfig):
    """Run the local repository commit workflow."""
    # Prompt for repository path
    repo_path = prompt_for_path("Enter the path to your git repository:")
    console.print()

    # Validate the path exists
    if not os.path.isdir(repo_path):
        show_error(f"Directory does not exist: {repo_path}")
        return

    console.print(f"[dim]Using path: {repo_path}[/dim]")

    # Initialize git operations
    try:
        git_ops = GitOperations(repo_path=repo_path)
    except NotAGitRepositoryError as e:
        show_error(str(e))
        return

    console.print(f"[dim]Repository: {git_ops.get_repo_name()}[/dim]")
    console.print(f"[dim]Branch: {git_ops.get_current_branch()}[/dim]")
    console.print()

    # Check for staged changes
    try:
        git_ops.validate_staged_changes()
    except NoStagedChangesError as e:
        show_error(str(e))

        # Offer to show unstaged changes
        unstaged = git_ops.get_unstaged_changes()
        untracked = git_ops.get_untracked_files()

        if unstaged or untracked:
            console.print()
            console.print("[bold]Uncommitted changes:[/bold]")
            for f in unstaged[:10]:
                console.print(f"    [yellow]modified:[/yellow] {f}")
            for f in untracked[:10]:
                console.print(f"    [green]untracked:[/green] {f}")
            if len(unstaged) + len(untracked) > 20:
                console.print(f"    [dim]... and more[/dim]")
            console.print()
            console.print("[dim]Use 'git add <file>' to stage changes.[/dim]")
        return

    # Get and display staged changes
    staged = git_ops.get_staged_changes()
    metrics = git_ops.analyze_change_complexity()
    display_staged_changes(staged, metrics)

    # Check for potential split
    splitter = CommitSplitter(
        max_commit_size=config.max_commit_size,
        complexity_threshold=config.complexity_threshold,
    )
    proposal = splitter.analyze(staged, metrics)

    groups_to_process = []
    if proposal.should_split:
        should_split = display_split_proposal(proposal)
        if should_split:
            groups_to_process = proposal.groups
            show_warning(
                "Note: Automatic staging for splits is not implemented. "
                "You'll need to manually stage files for each commit."
            )
            console.print()

    # Initialize commit generator
    try:
        generator = CommitGenerator(config)
    except CommitGeneratorError as e:
        show_error(str(e))
        return

    # Generate commit message(s)
    if groups_to_process:
        # Generate messages for each group
        with console.status("[cyan]Generating commit messages...[/cyan]"):
            commits = generator.generate_split_commits(groups_to_process)

        for i, (group, commit) in enumerate(zip(groups_to_process, commits), 1):
            console.print(f"\n[bold]Commit {i}/{len(commits)}: {group.name}[/bold]")
            diff_summary = (
                f"Files: {group.file_count} | "
                f"Changes: +{group.total_additions} -{group.total_deletions}"
            )
            display_commit_preview(commit, diff_summary)

        console.print()
        console.print(
            "[yellow]Please manually stage and commit each group.[/yellow]"
        )
        console.print("[dim]The suggested messages are shown above.[/dim]")
    else:
        # Generate single commit message
        file_paths = [f.file_path for f in staged.files]

        with console.status("[cyan]Generating commit message with AI...[/cyan]"):
            try:
                commit = generator.generate_commit_message(
                    diff_content=staged.diff_content,
                    file_paths=file_paths,
                )
            except CommitGeneratorError as e:
                show_error(f"Failed to generate commit message: {e}")
                return

        diff_summary = (
            f"Files: {metrics.total_files} | "
            f"Changes: +{staged.total_additions} -{staged.total_deletions}"
        )

        while True:
            display_commit_preview(commit, diff_summary)

            choice = request_user_approval()

            if choice == "approve":
                # Create the commit
                result = git_ops.create_commit(commit.formatted_message)
                if result.success:
                    display_commit_result(git_ops, result.sha)
                else:
                    show_error(result.error or "Commit failed")
                break

            elif choice == "edit":
                edited = edit_commit_message(commit.formatted_message)
                # Update the commit object
                commit.formatted_message = edited
                # Re-display for final approval
                continue

            elif choice == "regenerate":
                feedback = Prompt.ask(
                    "[bold]Any feedback for regeneration?[/bold]",
                    default="",
                )
                with console.status("[cyan]Regenerating commit message...[/cyan]"):
                    try:
                        if feedback:
                            commit = generator.regenerate_with_feedback(
                                commit.formatted_message,
                                feedback,
                                staged.diff_content,
                                file_paths,
                            )
                        else:
                            commit = generator.generate_commit_message(
                                staged.diff_content, file_paths
                            )
                    except CommitGeneratorError as e:
                        show_error(f"Regeneration failed: {e}")
                        continue
                continue

            else:  # cancel
                console.print()
                console.print("[dim]Commit cancelled. No changes were made.[/dim]")
                break


def run_github_workflow(config: CommitConfig):
    """Run the GitHub repository workflow."""
    # Validate GitHub config
    is_valid, errors = config.validate_github()
    if not is_valid:
        for error in errors:
            show_error(error)
        return

    # Initialize GitHub client
    try:
        client = GitHubClient(config.github_token, config.github_per_page)
        console.print(f"[dim]Authenticated as: {client.username}[/dim]")
        console.print()
    except GitHubAuthError as e:
        show_error(str(e))
        return
    except GitHubClientError as e:
        show_error(str(e))
        return

    # Select repository
    repo = select_github_repository(client)
    if not repo:
        return

    console.print()
    console.print(f"[bold]Selected:[/bold] [green]{repo.full_name}[/green]")

    # Select branch
    branch = select_branch(client, repo.full_name)
    if not branch:
        return

    console.print(f"[bold]Branch:[/bold] [green]{branch.name}[/green]")

    # Select commits
    commits = select_commits(client, repo.full_name, branch.name)
    if not commits:
        console.print("[dim]No commits selected.[/dim]")
        return

    console.print()
    console.print(f"[bold]Selected {len(commits)} commit(s)[/bold]")

    # Get diffs for selected commits
    with console.status("[cyan]Fetching commit diffs...[/cyan]"):
        try:
            diffs = client.get_multiple_commit_diffs(
                repo.full_name, [c.sha for c in commits]
            )
        except GitHubClientError as e:
            show_error(str(e))
            return

    # Aggregate diff content
    total_additions = sum(d.additions for d in diffs)
    total_deletions = sum(d.deletions for d in diffs)
    all_files = []
    all_patches = []

    for diff in diffs:
        all_files.extend(f["filename"] for f in diff.files)
        all_patches.append(diff.patch)

    combined_diff = "\n\n".join(all_patches)

    console.print()
    console.print("[bold]Aggregated Changes:[/bold]")
    console.print(f"    Files: {len(set(all_files))}")
    console.print(f"    Lines: [green]+{total_additions}[/green] [red]-{total_deletions}[/red]")
    console.print()

    # Generate commit message
    try:
        generator = CommitGenerator(config)
    except CommitGeneratorError as e:
        show_error(str(e))
        return

    with console.status("[cyan]Generating commit message with AI...[/cyan]"):
        try:
            context = {
                "existing_messages": [c.message for c in commits[:3]],
                "project_type": "github",
                "language": repo.language,
            }
            commit = generator.generate_commit_message(
                diff_content=combined_diff,
                file_paths=list(set(all_files)),
                context=context,
            )
        except CommitGeneratorError as e:
            show_error(f"Failed to generate commit message: {e}")
            return

    diff_summary = (
        f"Based on {len(commits)} commit(s) | "
        f"Files: {len(set(all_files))} | "
        f"Changes: +{total_additions} -{total_deletions}"
    )

    display_commit_preview(commit, diff_summary)

    console.print()
    console.print("[bold]Generated message (for reference):[/bold]")
    console.print("[dim]This message is based on the selected GitHub commits.[/dim]")
    console.print()

    # Display the raw commit message as output
    console.print("[bold cyan]─── Commit Message ───[/bold cyan]")
    console.print()
    console.print(commit.formatted_message)
    console.print()
    console.print("[bold cyan]──────────────────────[/bold cyan]")
    console.print()

    # Copy option
    try:
        if Confirm.ask("Copy message to clipboard?", default=False):
            try:
                import subprocess
                # Try xclip (Linux)
                process = subprocess.Popen(
                    ["xclip", "-selection", "clipboard"],
                    stdin=subprocess.PIPE,
                )
                process.communicate(commit.formatted_message.encode())
                show_success("Message copied to clipboard!")
            except (FileNotFoundError, Exception):
                console.print("[dim]Clipboard not available. Message printed above.[/dim]")
    except (EOFError, KeyboardInterrupt):
        pass


def select_gitlab_repository(client: GitLabClient) -> Optional[GitLabRepoInfo]:
    """
    Interactive repository selection from GitLab.

    Args:
        client: GitLab client instance.

    Returns:
        Selected RepositoryInfo or None if cancelled.
    """
    with console.status("[cyan]Fetching projects from GitLab...[/cyan]"):
        try:
            repos = client.list_repositories()
        except GitLabClientError as e:
            show_error(str(e))
            return None

    if not repos:
        show_warning("No projects found.")
        return None

    console.print(f"[green]Found {len(repos)} project(s).[/green]")
    console.print()

    # Display repository table
    table = Table(title="Your GitLab Projects", box=None, padding=(0, 1))
    table.add_column("#", justify="right", width=4, style="dim")
    table.add_column("Project", width=40)
    table.add_column("Language", width=12)
    table.add_column("Stars", justify="right", width=6)
    table.add_column("Updated", width=12)

    for i, repo in enumerate(repos[:30], 1):
        visibility = "[dim](private)[/dim]" if repo.private else ""
        updated = repo.updated_at.strftime("%Y-%m-%d") if repo.updated_at else "N/A"
        table.add_row(
            str(i),
            f"{repo.full_name} {visibility}",
            repo.language or "-",
            str(repo.stars),
            updated,
        )

    console.print(table)

    if len(repos) > 30:
        console.print(f"[dim]Showing first 30 of {len(repos)} projects.[/dim]")

    console.print()

    try:
        choice = Prompt.ask(
            "[bold]Enter number to select, or type to search[/bold]"
        )

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(repos):
                return repos[idx]
            show_error("Invalid selection.")
            return None
        else:
            # Search by name
            matches = [r for r in repos if choice.lower() in r.full_name.lower()]
            if len(matches) == 1:
                return matches[0]
            elif len(matches) > 1:
                console.print(f"[yellow]Multiple matches found:[/yellow]")
                for i, repo in enumerate(matches[:10], 1):
                    console.print(f"  [{i}] {repo.full_name}")
                sub_choice = Prompt.ask("Select number", default="1")
                idx = int(sub_choice) - 1
                if 0 <= idx < len(matches):
                    return matches[idx]
            else:
                show_warning("No matching projects found.")
                return None

    except (EOFError, KeyboardInterrupt):
        return None


def select_gitlab_branch(client: GitLabClient, project_id: int, default_branch: str) -> Optional[GitLabBranchInfo]:
    """
    Interactive branch selection for GitLab.

    Args:
        client: GitLab client instance.
        project_id: GitLab project ID.
        default_branch: Default branch name.

    Returns:
        Selected BranchInfo or None if cancelled.
    """
    with console.status("[cyan]Fetching branches...[/cyan]"):
        try:
            branches = client.list_branches(project_id)
        except GitLabClientError as e:
            show_error(str(e))
            return None

    if not branches:
        show_warning("No branches found.")
        return None

    console.print()
    console.print("[bold]Select branch:[/bold]")
    console.print()

    for i, branch in enumerate(branches[:20], 1):
        indicators = []
        if branch.is_default:
            indicators.append("[green]default[/green]")
        if branch.is_protected:
            indicators.append("[yellow]protected[/yellow]")
        indicator_str = f" ({', '.join(indicators)})" if indicators else ""
        console.print(f"    [green][{i}][/green] {branch.name}{indicator_str}")

    console.print()

    try:
        choice = Prompt.ask(
            "[bold]Enter choice[/bold]",
            default="1",
        )
        idx = int(choice) - 1
        if 0 <= idx < len(branches):
            return branches[idx]
        show_error("Invalid selection.")
        return None
    except (EOFError, KeyboardInterrupt, ValueError):
        return None


def select_gitlab_commits(
    client: GitLabClient, project_id: int, branch_name: str
) -> List[GitLabCommitInfo]:
    """
    Interactive commit selection for GitLab (multi-select).

    Args:
        client: GitLab client instance.
        project_id: GitLab project ID.
        branch_name: Branch name.

    Returns:
        List of selected CommitInfo objects.
    """
    with console.status("[cyan]Fetching commits...[/cyan]"):
        try:
            commits = client.list_commits(project_id, branch_name, limit=50)
        except GitLabClientError as e:
            show_error(str(e))
            return []

    if not commits:
        show_warning("No commits found.")
        return []

    console.print()
    console.print("[bold]Select commits to analyze:[/bold]")
    console.print("[dim]Enter numbers separated by spaces, or 'all' for all commits[/dim]")
    console.print()

    table = Table(box=None, padding=(0, 1))
    table.add_column("#", justify="right", width=3, style="dim")
    table.add_column("SHA", width=8, style="yellow")
    table.add_column("Message", width=50)
    table.add_column("Author", width=15)
    table.add_column("Date", width=12)

    for i, commit in enumerate(commits[:30], 1):
        message = commit.message.split("\n")[0][:48]
        date = commit.date.strftime("%Y-%m-%d") if commit.date else "N/A"
        table.add_row(
            str(i),
            commit.short_sha,
            message,
            commit.author_name[:14],
            date,
        )

    console.print(table)
    console.print()

    try:
        choice = Prompt.ask("[bold]Enter selection[/bold]", default="1")

        if choice.lower() == "all":
            return commits[:30]

        # Parse selection
        selected = []
        for part in choice.split():
            if "-" in part:
                # Range selection (e.g., "1-5")
                start, end = part.split("-")
                for i in range(int(start), int(end) + 1):
                    if 1 <= i <= len(commits):
                        selected.append(commits[i - 1])
            else:
                idx = int(part) - 1
                if 0 <= idx < len(commits):
                    selected.append(commits[idx])

        return selected

    except (EOFError, KeyboardInterrupt, ValueError):
        return []


def run_quick_commit(config: CommitConfig):
    """
    Run a quick, non-interactive commit workflow.

    Auto-detects the current repository, generates a commit message,
    and creates the commit with minimal user interaction.
    """
    # Initialize git operations for current directory
    try:
        git_ops = GitOperations()
    except NotAGitRepositoryError as e:
        show_error(str(e))
        return False

    console.print(f"[dim]Repository:[/dim] {git_ops.get_repo_name()}")
    console.print(f"[dim]Branch:[/dim] {git_ops.get_current_branch()}")
    console.print()

    # Check for staged changes
    try:
        git_ops.validate_staged_changes()
    except NoStagedChangesError as e:
        show_error(str(e))

        # Show unstaged/untracked files hint
        unstaged = git_ops.get_unstaged_changes()
        untracked = git_ops.get_untracked_files()

        if unstaged or untracked:
            console.print()
            console.print("[bold]Uncommitted changes detected:[/bold]")
            for f in unstaged[:5]:
                console.print(f"    [yellow]modified:[/yellow] {f}")
            for f in untracked[:5]:
                console.print(f"    [green]untracked:[/green] {f}")
            if len(unstaged) + len(untracked) > 10:
                console.print(f"    [dim]... and more[/dim]")
            console.print()
            console.print("[dim]Stage changes with 'git add <file>' first.[/dim]")
        return False

    # Get staged changes
    staged = git_ops.get_staged_changes()
    metrics = git_ops.analyze_change_complexity()

    # Show brief summary
    console.print(f"[bold]Staged:[/bold] {metrics.total_files} file(s), "
                  f"[green]+{staged.total_additions}[/green] [red]-{staged.total_deletions}[/red] lines")
    console.print()

    # Initialize commit generator
    try:
        generator = CommitGenerator(config)
    except CommitGeneratorError as e:
        show_error(str(e))
        return False

    # Generate commit message
    file_paths = [f.file_path for f in staged.files]

    with console.status("[cyan]Generating commit message...[/cyan]"):
        try:
            commit = generator.generate_commit_message(
                diff_content=staged.diff_content,
                file_paths=file_paths,
            )
        except CommitGeneratorError as e:
            show_error(f"Failed to generate commit message: {e}")
            return False

    # Display commit message
    console.print(Panel(
        commit.formatted_message,
        title=f"[green]{commit.type.type_name.upper()}[/green] Commit Message",
        border_style="green",
        padding=(1, 2),
    ))
    console.print()

    # Simple approval
    try:
        approve = Confirm.ask("Create this commit?", default=True)

        if approve:
            result = git_ops.create_commit(commit.formatted_message)
            if result.success:
                console.print()
                show_success(f"Commit created: {result.sha[:8]}")
                console.print()
                # Show brief commit info
                console.print(f"[dim]{git_ops.get_repo_name()}[/dim] [bold]{git_ops.get_current_branch()}[/bold]")
                return True
            else:
                show_error(result.error or "Commit failed")
                return False
        else:
            console.print("[dim]Commit cancelled.[/dim]")
            return False

    except (EOFError, KeyboardInterrupt):
        console.print("\n[dim]Cancelled.[/dim]")
        return False


def run_gitlab_workflow(config: CommitConfig):
    """Run the GitLab repository workflow."""
    # Validate GitLab config
    is_valid, errors = config.validate_gitlab()
    if not is_valid:
        for error in errors:
            show_error(error)
        return

    # Initialize GitLab client
    try:
        client = GitLabClient(
            token=config.gitlab_token,
            url=config.gitlab_url,
            per_page=config.gitlab_per_page,
        )
        console.print(f"[dim]Authenticated as: {client.username}[/dim]")
        console.print(f"[dim]GitLab: {client.gitlab_url}[/dim]")
        console.print()
    except GitLabAuthError as e:
        show_error(str(e))
        return
    except GitLabClientError as e:
        show_error(str(e))
        return

    # Select repository
    repo = select_gitlab_repository(client)
    if not repo:
        return

    console.print()
    console.print(f"[bold]Selected:[/bold] [green]{repo.full_name}[/green]")

    # Select branch
    branch = select_gitlab_branch(client, repo.id, repo.default_branch)
    if not branch:
        return

    console.print(f"[bold]Branch:[/bold] [green]{branch.name}[/green]")

    # Select commits
    commits = select_gitlab_commits(client, repo.id, branch.name)
    if not commits:
        console.print("[dim]No commits selected.[/dim]")
        return

    console.print()
    console.print(f"[bold]Selected {len(commits)} commit(s)[/bold]")

    # Get diffs for selected commits
    with console.status("[cyan]Fetching commit diffs...[/cyan]"):
        try:
            diffs = client.get_multiple_commit_diffs(
                repo.id, [c.sha for c in commits]
            )
        except GitLabClientError as e:
            show_error(str(e))
            return

    # Aggregate diff content
    total_additions = sum(d.additions for d in diffs)
    total_deletions = sum(d.deletions for d in diffs)
    all_files = []
    all_patches = []

    for diff in diffs:
        all_files.extend(f["filename"] for f in diff.files)
        all_patches.append(diff.patch)

    combined_diff = "\n\n".join(all_patches)

    console.print()
    console.print("[bold]Aggregated Changes:[/bold]")
    console.print(f"    Files: {len(set(all_files))}")
    console.print(f"    Lines: [green]+{total_additions}[/green] [red]-{total_deletions}[/red]")
    console.print()

    # Generate commit message
    try:
        generator = CommitGenerator(config)
    except CommitGeneratorError as e:
        show_error(str(e))
        return

    with console.status("[cyan]Generating commit message with AI...[/cyan]"):
        try:
            context = {
                "existing_messages": [c.message for c in commits[:3]],
                "project_type": "gitlab",
                "language": repo.language,
            }
            commit = generator.generate_commit_message(
                diff_content=combined_diff,
                file_paths=list(set(all_files)),
                context=context,
            )
        except CommitGeneratorError as e:
            show_error(f"Failed to generate commit message: {e}")
            return

    diff_summary = (
        f"Based on {len(commits)} commit(s) | "
        f"Files: {len(set(all_files))} | "
        f"Changes: +{total_additions} -{total_deletions}"
    )

    display_commit_preview(commit, diff_summary)

    console.print()
    console.print("[bold]Generated message (for reference):[/bold]")
    console.print("[dim]This message is based on the selected GitLab commits.[/dim]")
    console.print()

    # Display the raw commit message as output
    console.print("[bold cyan]─── Commit Message ───[/bold cyan]")
    console.print()
    console.print(commit.formatted_message)
    console.print()
    console.print("[bold cyan]──────────────────────[/bold cyan]")
    console.print()

    # Copy option
    try:
        if Confirm.ask("Copy message to clipboard?", default=False):
            try:
                import subprocess
                # Try xclip (Linux)
                process = subprocess.Popen(
                    ["xclip", "-selection", "clipboard"],
                    stdin=subprocess.PIPE,
                )
                process.communicate(commit.formatted_message.encode())
                show_success("Message copied to clipboard!")
            except (FileNotFoundError, Exception):
                console.print("[dim]Clipboard not available. Message printed above.[/dim]")
    except (EOFError, KeyboardInterrupt):
        pass


def print_commit_help():
    """Print help message for the commit CLI."""
    print_banner()
    console.print("[bold]USAGE[/bold]")
    console.print("    git-commit-ai [OPTIONS]")
    console.print()
    console.print("[bold]OPTIONS[/bold]")
    console.print(
        "    [green]--quick, -q[/green]    Quick mode: auto-detect repo, generate and commit"
    )
    console.print(
        "    [green]--help, -h[/green]     Show this help message"
    )
    console.print()
    console.print("[dim]If no option is provided, interactive mode is used.[/dim]")
    console.print()


def main():
    """Main entry point for the commit CLI."""
    # Initialize input history for arrow key navigation
    setup_input_history()

    # Check for command line arguments
    quick_mode = False

    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg in ("--quick", "-q"):
            quick_mode = True
        elif arg in ("--help", "-h"):
            print_commit_help()
            return

    if not quick_mode:
        print_banner()

    # Load configuration
    try:
        config = CommitConfig.from_env()
    except Exception as e:
        show_error(f"Failed to load configuration: {e}")
        console.print()
        console.print("[dim]Create a .env file with your API keys.[/dim]")
        console.print("[dim]See .env.example for configuration options.[/dim]")
        sys.exit(1)

    # Validate OpenAI configuration (required for all workflows)
    is_valid, errors = config.validate_openai()
    if not is_valid:
        for error in errors:
            show_error(error)
        console.print()
        console.print("[dim]Set OPENAI_API_KEY in your .env file.[/dim]")
        sys.exit(1)

    # Quick mode - skip menu, auto-detect and commit
    if quick_mode:
        success = run_quick_commit(config)
        sys.exit(0 if success else 1)

    # Show main menu
    choice = show_main_menu()

    console.print()

    if choice == "local":
        run_local_workflow(config)
    elif choice == "github":
        run_github_workflow(config)
    else:
        run_gitlab_workflow(config)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[dim]Interrupted.[/dim]")
        sys.exit(0)
    except Exception as e:
        console.print(f"[red]Unexpected error:[/red] {e}")
        sys.exit(1)
