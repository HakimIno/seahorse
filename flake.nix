{
  description = "Seahorse: High-Performance AI Agent Framework";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    rust-overlay.url = "github:oxalica/rust-overlay";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, rust-overlay, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        overlays = [ (import rust-overlay) ];
        pkgs = import nixpkgs {
          inherit system overlays;
        };
        
        rustToolchain = pkgs.rust-bin.stable.latest.default.override {
          extensions = [ "rust-src" "rust-analyzer" "clippy" ];
        };

        # Essential tools for the project
        nativeBuildInputs = with pkgs; [
          pkg-config
          rustToolchain
          uv
          sccache
          maturin
          cargo-nextest
          python312
          ncurses
          lsof
        ];

        # Libraries required at runtime or link-time
        buildInputs = with pkgs; [
          openssl
          zlib
        ] ++ lib.optionals stdenv.isDarwin [
          apple-sdk
          libiconv
        ];
      in
      {
        devShells.default = pkgs.mkShell {
          inherit nativeBuildInputs buildInputs;

          shellHook = ''
            # Set OpenSSL environment variables for Rust's openssl-sys crate
            export OPENSSL_DIR="${pkgs.openssl.dev}"
            export OPENSSL_LIB_DIR="${pkgs.openssl.out}/lib"
            export OPENSSL_INCLUDE_DIR="${pkgs.openssl.dev}/include"
            
            # Ensure Python environment is clean and uses uv
            export PYTHONNOUSERSITE=1
            
            echo "🌊 Seahorse development environment loaded!"
            echo "Rust: $(rustc --version)"
            echo "Python: $(python3 --version)"
            echo "uv: $(uv --version)"
          '';
        };
      }
    );
}
