"""Explicit offline entry point; does not load MEMESCOPE application settings."""
from __future__ import annotations
import json
from pathlib import Path
import sys

LAB = Path(__file__).resolve().parent
ARTIFACTS = LAB / 'artifacts'


def output_path(value: str) -> str:
    """All lab command writes stay in the lab's artifacts directory."""
    root = ARTIFACTS.resolve()
    if ARTIFACTS.is_symlink():
        raise ValueError('artifacts directory must not be a symlink')
    path = Path(value).expanduser().resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError(f'output must be inside {root}')
    return str(path)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ['status']:
        print(json.dumps({'lab': 'pretrade_ai', 'mode': 'offline_advisory_only',
                          'automatic_execution': False, 'wallet_connected': False,
                          'database_connected': False, 'live_mapping': 'unresolved',
                          'artifacts': str(ARTIFACTS)}, indent=2))
        return 0
    if argv == ['demo']:
        from .demo import run_demo
        run_demo()
        return 0
    # Kept local to the explicit command; importing the lab never imports ML libraries.
    sys.path.insert(0, str(LAB / 'src'))
    try:
        from memescope_pretrade_ai.cli import main as run, parser
    except ModuleNotFoundError as exc:
        raise SystemExit('Install and use this lab’s .venv; see pretrade_ai/README.md.') from exc
    if not argv or argv in [['--help'], ['-h']]:
        print('Additional lab commands: status, demo. All outputs stay in lab/artifacts/.')
        parser().print_help()
        return 0
    if argv[0] in {'train', 'score', 'backtest'} and not any(
        item == '--config' or item.startswith('--config=') for item in argv
    ):
        argv += ['--config', str(LAB / 'config/default.yaml')]
    args = parser().parse_args(argv)
    for field in ('output', 'output_dir'):
        value = getattr(args, field, None)
        if value is not None:
            setattr(args, field, output_path(value))
    if getattr(args, 'model', None):
        # joblib is executable serialization. Only load models from this lab's local output.
        args.model = output_path(args.model)
    normalized = [args.command]
    for field, value in vars(args).items():
        if field == 'command' or value is None or value is False:
            continue
        normalized.append('--' + field.replace('_', '-'))
        if value is not True:
            normalized.append(str(value))
    run(normalized)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
