# Building the environment (macOS Apple Silicon / arm64)

The non-engine stack installs cleanly from `requirements.txt`. **RocketCEA** (the
engine path) is the exception: it compiles a Fortran extension, and on Apple
Silicon the build needs an arm64 Fortran toolchain plus explicit `-arch arm64`
flags, or it silently produces an **x86_64** `.so` that fails to import.

## 1. Use an arm64 Python

The committed pins (numpy ≥ 2.4.x) require **Python ≥ 3.11**. Use a clean arm64
interpreter — e.g. Homebrew's:

```bash
/opt/homebrew/bin/python3.11 -c 'import platform; print(platform.machine())'   # -> arm64
```

## 2. Create the venv and install the base stack

```bash
/opt/homebrew/bin/python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt   # everything except rocketcea
```

## 3. Install an arm64 Fortran compiler

The default `gfortran` on this machine is **x86_64** (`/usr/local/bin/gfortran`,
from the x86_64 Homebrew). Install the arm64 one via the arm64 Homebrew:

```bash
arch -arm64 /opt/homebrew/bin/brew install gcc            # provides /opt/homebrew/bin/gfortran (arm64)
file -b "$(readlink -f /opt/homebrew/bin/gfortran)"        # -> Mach-O 64-bit executable arm64
```

Note: the arm64 `gfortran` is *shadowed* on PATH by the x86_64 one, so the build
must point at it explicitly (below).

## 4. Build RocketCEA for arm64

The decisive part: RocketCEA builds with meson, and meson otherwise links the C
object as x86_64 (discarding the arm64 Fortran objects → an empty x86_64 bundle).
Force `-arch arm64` into both the C and Fortran compile/link args, and put the
arm64 `gfortran` first on PATH:

```bash
PATH="/opt/homebrew/bin:$PATH" FC=/opt/homebrew/bin/gfortran \
.venv/bin/python -m pip install rocketcea==1.2.3 \
  --no-cache-dir --no-binary rocketcea \
  --config-settings=setup-args="-Dc_args=-arch arm64" \
  --config-settings=setup-args="-Dc_link_args=-arch arm64" \
  --config-settings=setup-args="-Dfortran_args=-arch arm64" \
  --config-settings=setup-args="-Dfortran_link_args=-arch arm64"
```

## 5. Verify

```bash
# the compiled extension must be arm64:
file -b .venv/lib/python3.11/site-packages/rocketcea/py_cea.cpython-311-darwin.so   # -> ... arm64

.venv/bin/python -c "from rocketcea.cea_obj import CEA_Obj; \
print(round(CEA_Obj(oxName='LOX', fuelName='CH4').get_Isp(Pc=2000, MR=3.5, eps=40),1), 's')"  # ~369.7 s

.venv/bin/python -m unittest tests.test_loop tests.test_network_io tests.test_fluid_network_mcp   # 30 tests OK
```

If the `.so` is `x86_64`, the `-arch arm64` flags or the arm64 `gfortran` didn't
take — re-check steps 3–4 (and that `which gfortran` under the build PATH is the
`/opt/homebrew` one).
