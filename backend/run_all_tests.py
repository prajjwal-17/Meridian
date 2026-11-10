
import argparse
import os
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
APP_DIR = BASE_DIR / "app"
SCRIPTS_DIR = BASE_DIR / "scripts"


def run_command(name, command):
    print("\n" + "=" * 65)
    print(f"RUNNING: {name}")
    print("=" * 65)

    env = os.environ.copy()

    # Make backend/app importable from scripts
    env["PYTHONPATH"] = (
        str(BASE_DIR)
        + os.pathsep
        + env.get("PYTHONPATH", "")
    )

    result = subprocess.run(
        command,
        cwd=BASE_DIR,
        env=env,
        text=True
    )

    if result.returncode == 0:
        print(f"\n[PASS] {name}")
        return True

    print(f"\n[FAIL] {name} (exit code: {result.returncode})")
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Run Meridian backend tests"
    )

    parser.add_argument(
        "--acl-manifest",
        help="Path to the ACL test manifest JSON file"
    )

    args = parser.parse_args()

    results = []

    # 1. Compile application and scripts
    print("\nCompiling Python files...")

    compile_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "compileall",
            "-q",
            str(APP_DIR),
            str(SCRIPTS_DIR)
        ],
        cwd=BASE_DIR
    )

    results.append(
        ("Compilation", compile_result.returncode == 0)
    )

    # 2. Discover test scripts
    test_files = sorted(SCRIPTS_DIR.glob("test_*.py"))

    acl_test = SCRIPTS_DIR / "test_scifact_acl.py"

    for test_file in test_files:

        # ACL test requires a manifest
        if test_file == acl_test:

            if not args.acl_manifest:
                print(
                    f"\n[SKIP] {test_file.name}: "
                    "requires --acl-manifest"
                )
                continue

            manifest_path = Path(args.acl_manifest)

            if not manifest_path.is_absolute():
                manifest_path = (Path.cwd() / manifest_path).resolve()

            if not manifest_path.exists():
                print(
                    f"\n[SKIP] {test_file.name}: "
                    f"manifest not found: {manifest_path}"
                )
                continue

            command = [
                sys.executable,
                str(test_file),
                "--manifest",
                str(manifest_path)
            ]

        else:
            command = [
                sys.executable,
                str(test_file)
            ]

        passed = run_command(test_file.name, command)
        results.append((test_file.name, passed))

    # 3. Final summary
    print("\n" + "=" * 65)
    print("MERIDIAN TEST SUMMARY")
    print("=" * 65)

    passed_count = 0
    failed_count = 0

    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"{status:8} {name}")

        if passed:
            passed_count += 1
        else:
            failed_count += 1

    print("\n" + "-" * 65)
    print(f"Passed: {passed_count}")
    print(f"Failed: {failed_count}")
    print("-" * 65)

    if failed_count:
        print("\nSome tests failed. Check the output above.")
        sys.exit(1)

    print("\nAll executed tests passed.")


if __name__ == "__main__":
    main()
