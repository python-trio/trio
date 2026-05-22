# An "impure" template thx to `pyproject.nix`,
# https://pyproject-nix.github.io/pyproject.nix/templates.html#impure
# https://github.com/pyproject-nix/pyproject.nix/blob/master/templates/impure/flake.nix
{
  description = "An impure dev-shell (overlay) using `uv`";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable-small";
  };

  outputs =
    { nixpkgs, ... }:
    let
      inherit (nixpkgs) lib;
      forAllSystems = lib.genAttrs lib.systems.flakeExposed;
    in
    {
      devShells = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};

          # XXX NOTE XXX, for now we overlay specific pkgs via
          # a major-version-pinned-`cpython`
          cpython = "python313";
          venv_dir = "py313";
          pypkgs = pkgs."${cpython}Packages";
        in
        {
          default = pkgs.mkShell {

            packages = [
              # XXX, ensure sh completions activate!
              pkgs.bashInteractive
              pkgs.bash-completion

              # pkgs.xonsh
              pkgs.uv
              pkgs.${cpython} # ?TODO^ how to set from `cpython` above?
              pkgs."${cpython}Packages".setuptools

              # testing-n-tooling
              # ?TODO, if we want to pull `xxx-requirements.txt` from
              # nixpkgs directly?
              # - [ ] extract-n-translate all `[docs|test]-requirements.txt` deps
              #      into their equiv nxpkgs equivalents.
              #
              # For ex. we can explicitily add them like the below,
              # but ideally we use a translator lib (like
              # `pyproject.nix` and/or `uv2nix`).
              #
              # pkgs."${cpython}Packages".black
              # pkgs."${cpython}Packages".coverage
              # pkgs."${cpython}Packages".hypothesis
              # pkgs."${cpython}Packages".mypy
              # pkgs."${cpython}Packages".pytest
              # pkgs."${cpython}Packages".towncrier

              # XXX, pkgs not listed in `-requirements.txt` files.
              pkgs."${cpython}Packages".tox

              # XXX, on nix(os), use pkgs version to avoid
              # build/sys-sh-integration issues
              pkgs.ruff
              pkgs.pyright

            ];

            shellHook = ''
              # unmask to debug **this** dev-shell-hook
              # set -e

              # RUNTIME-SETTINGS
              # ------ uv ------
              # - always use and explicit py-version abbreviated
              #   `${venv_dir}` (like `./py313/`) venv-subdir instead
              #   the default (and version ambiguous) `.venv` used by
              #   `uv`.
              export UV_PROJECT_ENVIRONMENT=${venv_dir}

              # - sync the `uv` env with all extras, namely the test
              #   and docs deps as required by the full CI/CD
              #   pipeline used on Github.
              uv add -r test-requirements.in -c test-requirements.txt --group test

              # ?TODO? next line is unneeded since
              # `test-requirements.[in|txt]` already is super set of
              # `docs-requirements.[in|txt]`?
              # uv add -r docs-requirements.in -c docs-requirements.txt --group docs

              # NOTE, a `tox.ini` is included in repo even though no
              # explicit dependency is declared elsewhere.
              uv add --group test tox

              # generate a `uv.lock`
              uv lock

              # ?TODO, this would update to latest deps versions right?
              # - [ ] a dev can invoke this explicitly if wanted?
              # uv sync

              # ?TODO? if core-devs would prefer not (encouraging us)
              # to use `uv` we can instead use `pip` directly, but it
              # seems a bit pedantic and less convenient when devving
              # on nix(os).
              # pip install -e .

              # ------ HOT-TIPS ------
              # - to launch the py-venv installed `xonsh` (like your
              #   fave collab @goodboy) run the `nix develop` cmd with,
              # >> nix develop -c uv run xonsh
            '';
          };
        }
      );
    };
}
