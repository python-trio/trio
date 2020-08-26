{ pkgs ? import <nixpkgs> {}}:

pkgs.python37Packages.trio.overrideAttrs (oldAttrs: {
  src = ./.;
})
