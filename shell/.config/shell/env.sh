# Environment variables (bash/zsh). Sourced from ~/.bashrc.

# Nx: no background daemon, cap parallelism at nproc-2 (min 1).
export NX_DAEMON=false
export NX_PARALLEL=$(( $(nproc) - 2 > 0 ? $(nproc) - 2 : 1 ))
