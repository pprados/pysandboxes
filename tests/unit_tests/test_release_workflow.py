# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Structure of .github/workflows/release.yml: publication waits for every gate.

A guard against an honest mistake in the workflow, not against an attack: whoever can change release.yml can
change this test too. What stops a malicious change is outside the repository (tag ruleset, testpypi reviewer, dockerhub
environment).
"""

from pathlib import Path
from typing import Any

import yaml

WORKFLOW = Path(__file__).parents[2] / ".github" / "workflows" / "release.yml"
GATES = {"verify", "build", "reuse-lookup", "full-gate", "wheel-tests"}
GATE = (
    "!cancelled() && needs.build.result == 'success' && needs.wheel-tests.result == 'success' "
    "&& needs.reuse-lookup.result == 'success' "
    "&& (needs.reuse-lookup.outputs.reuse == 'true' || needs.full-gate.result == 'success')"
)


def _jobs() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]


def _needs(job: dict[str, Any]) -> set[str]:
    needs = job.get("needs", [])
    return {needs} if isinstance(needs, str) else set(needs)


def _publish() -> dict[str, Any]:
    return _jobs()["publish-testpypi"]


def _condition() -> str:
    return " ".join(_publish()["if"].split())


def _condition_of(name: str) -> str:
    return " ".join(_jobs()[name]["if"].split())


def test_publication_needs_every_gate() -> None:
    assert _needs(_publish()) >= GATES


def test_publication_runs_in_the_reviewed_testpypi_environment() -> None:
    assert _publish()["environment"]["name"] == "testpypi"


def test_publication_requires_the_build_and_the_wheel_tests() -> None:
    condition = _condition()
    assert "!cancelled()" in condition
    assert "needs.build.result == 'success'" in condition
    assert "needs.wheel-tests.result == 'success'" in condition
    assert "needs.reuse-lookup.result == 'success'" in condition


def test_a_skipped_full_gate_passes_only_through_the_reuse_lookup() -> None:
    assert "(needs.reuse-lookup.outputs.reuse == 'true' || needs.full-gate.result == 'success')" in _condition()


def test_the_publication_condition_is_exactly_the_reviewed_one() -> None:
    assert _condition() == "${{ " + GATE + " && needs.verify.outputs.final == 'false' }}"


def test_a_final_tag_publishes_to_pypi_behind_the_same_gate() -> None:
    job = _jobs()["publish-pypi"]
    assert _needs(job) >= GATES
    assert job["environment"]["name"] == "pypi"
    assert job["permissions"] == {"id-token": "write"}
    assert _condition_of("publish-pypi") == "${{ " + GATE + " && needs.verify.outputs.final == 'true' }}"


def test_pypi_uploads_go_to_pypi_org_and_python_sb_only_when_it_changed() -> None:
    uploads = [s for s in _jobs()["publish-pypi"]["steps"] if "gh-action-pypi-publish" in s.get("uses", "")]
    assert [u["with"].get("packages-dir", "dist/") for u in uploads] == ["dist/", "dist-python-sb/"]
    assert all("repository-url" not in u["with"] for u in uploads)
    assert all(u["with"]["skip-existing"] is True for u in uploads)
    assert uploads[1]["if"] == PYTHON_SB


def test_the_full_gate_is_skipped_only_when_a_nightly_is_reused() -> None:
    full_gate = _jobs()["full-gate"]
    assert "reuse-lookup" in _needs(full_gate)
    assert full_gate["uses"] == "./.github/workflows/full-gate.yml"
    assert full_gate["if"] == "needs.reuse-lookup.outputs.reuse != 'true'"
    assert full_gate["with"]["exclude-tcg"] is True


def test_the_wheel_tests_run_on_every_claimed_interpreter() -> None:
    wheel_tests = _jobs()["wheel-tests"]
    assert "build" in _needs(wheel_tests)
    assert "if" not in wheel_tests
    assert wheel_tests["strategy"]["matrix"]["python-version"] == [
        "3.11",
        "3.12",
        "3.13",
        "3.14",
    ]


def test_the_reuse_lookup_reads_the_verified_commit() -> None:
    assert "verify" in _needs(_jobs()["reuse-lookup"])


def test_the_build_waits_for_the_light_gate() -> None:
    assert _needs(_jobs()["build"]) >= {"verify", "push-checks", "validate"}


def test_the_published_wheel_is_checked_only_after_a_publication() -> None:
    job = _jobs()["verify-published"]
    assert _needs(job) >= {"publish-testpypi", "publish-pypi"}
    assert _condition_of("verify-published") == (
        "${{ !cancelled() "
        "&& (needs.publish-testpypi.result == 'success' || needs.publish-pypi.result == 'success') }}"
    )


def test_a_final_release_is_checked_against_pypi_org() -> None:
    step = next(s for s in _jobs()["verify-published"]["steps"] if "verify-published.sh" in s.get("run", ""))
    assert step["env"]["INDEX_URL"] == (
        "${{ needs.verify.outputs.final == 'true' && 'https://pypi.org/simple/' || 'https://test.pypi.org/simple/' }}"
    )


def test_the_published_wheel_is_compared_with_the_built_artifact() -> None:
    steps = _jobs()["verify-published"]["steps"]
    assert any(s.get("with", {}).get("name") == "dist" for s in steps)
    assert any(".github/scripts/verify-published.sh" in s.get("run", "") for s in steps)


IMAGE_JOB = "images"


def _step_index(job: dict[str, Any], needle: str) -> int:
    return next(i for i, s in enumerate(job["steps"]) if needle in s.get("run", ""))


def test_the_images_follow_the_checked_publication() -> None:
    job = _jobs()[IMAGE_JOB]
    assert "verify-published" in _needs(job)
    assert " ".join(job["if"].split()) == (
        "${{ !cancelled() && vars.RELEASE_IMAGES != 'false' && needs.verify-published.result == 'success' }}"
    )


def test_the_images_push_from_the_tag_restricted_dockerhub_environment() -> None:
    assert _jobs()[IMAGE_JOB]["environment"] == "dockerhub"


def test_only_the_images_job_sees_the_docker_hub_secrets() -> None:
    for name, job in _jobs().items():
        if name != IMAGE_JOB:
            assert "DOCKERHUB" not in yaml.safe_dump(job), name


def test_the_images_job_asks_for_no_write_permission() -> None:
    assert "write" not in yaml.safe_dump(_jobs()[IMAGE_JOB].get("permissions", {}))


def test_the_smoke_test_runs_before_any_push() -> None:
    job = _jobs()[IMAGE_JOB]
    assert _step_index(job, "smoke-test-images.sh") < _step_index(job, "docker push")


def test_the_pushed_tags_come_only_from_image_tags_sh() -> None:
    push = _jobs()[IMAGE_JOB]["steps"][_step_index(_jobs()[IMAGE_JOB], "docker push")]["run"]
    assert '.github/scripts/image-tags.sh "$VERSION" "$IMAGE_PYTHON" "$DEFAULT_PYTHON"' in push
    assert 'docker tag "$image:$IMAGE_PYTHON" "$target"' in push
    assert "docker.io/pprados/$image:$tag" in push
    assert "latest" not in push


def test_the_images_are_published_for_every_claimed_interpreter() -> None:
    job = _jobs()[IMAGE_JOB]
    assert job["strategy"]["matrix"]["python-version"] == _jobs()["wheel-tests"]["strategy"]["matrix"]["python-version"]
    assert job["env"]["IMAGE_PYTHON"] == "${{ matrix.python-version }}"
    assert job["env"]["DEFAULT_PYTHON"] in job["strategy"]["matrix"]["python-version"]


def test_each_runner_builds_and_smoke_tests_its_own_python() -> None:
    job = _jobs()[IMAGE_JOB]
    build = job["steps"][_step_index(job, "build-images")]["run"]
    smoke = job["steps"][_step_index(job, "smoke-test-images.sh")]["run"]
    assert 'PYTHON_VERSION="$IMAGE_PYTHON"' in build
    assert '"$VERSION" "$IMAGE_PYTHON"' in smoke


PYTHON_SB = "needs.build.outputs.python-sb == 'true'"


def _steps_running(job: str, needle: str) -> list[dict[str, Any]]:
    return [s for s in _jobs()[job]["steps"] if needle in s.get("run", "") or needle in yaml.safe_dump(s)]


def test_the_build_decides_whether_python_sb_is_published() -> None:
    build = _jobs()["build"]
    assert build["outputs"]["python-sb"] == "${{ steps.python-sb.outputs.publish }}"
    step = next(s for s in build["steps"] if s.get("id") == "python-sb")
    assert '.github/scripts/python-sb-changes.sh "$GITHUB_REF_NAME"' in step["run"]


def test_python_sb_is_built_apart_from_the_pysandboxes_dist() -> None:
    build = _steps_running("build", "uv build python-sb")
    assert len(build) == 1
    assert build[0]["if"] == "steps.python-sb.outputs.publish == 'true'"
    assert "--out-dir dist-python-sb" in build[0]["run"]
    upload = next(s for s in _jobs()["build"]["steps"] if s.get("with", {}).get("name") == "python-sb")
    assert upload["with"]["path"] == "dist-python-sb/"
    assert upload["if"] == "steps.python-sb.outputs.publish == 'true'"


def test_the_python_sb_wheel_is_run_before_publication() -> None:
    steps = _steps_running("wheel-tests", "import sys, python_sb")
    assert len(steps) == 1
    assert steps[0]["if"] == PYTHON_SB


def test_python_sb_is_uploaded_only_when_it_changed() -> None:
    uploads = [s for s in _publish()["steps"] if "gh-action-pypi-publish" in s.get("uses", "")]
    assert [u["with"].get("packages-dir", "dist/") for u in uploads] == ["dist/", "dist-python-sb/"]
    assert uploads[1]["if"] == PYTHON_SB
    assert uploads[1]["with"]["repository-url"] == "https://test.pypi.org/legacy/"


def test_master_advances_only_after_a_final_release_is_published() -> None:
    job = _jobs()["advance-master"]
    assert _needs(job) >= {"verify", "verify-published", "images"}
    assert _condition_of("advance-master") == (
        "${{ !cancelled() && needs.verify.outputs.final == 'true' && needs.verify-published.result == 'success' "
        "&& (needs.images.result == 'success' || needs.images.result == 'skipped') }}"
    )
    assert job["permissions"] == {"contents": "write"}


def test_master_is_fast_forwarded_never_forced() -> None:
    runs = " ".join(s.get("run", "") for s in _jobs()["advance-master"]["steps"])
    assert 'git push origin "$SHA:refs/heads/master"' in runs
    assert "--force" not in runs and "+$SHA" not in runs and "-f " not in runs


def test_the_temporary_switch_skips_only_the_nightly_lookup() -> None:
    job = _jobs()["reuse-lookup"]
    step = next(s for s in job["steps"] if s.get("id") == "lookup")
    assert job["env"]["SKIP_FULL_GATE"] == "${{ vars.RELEASE_SKIP_FULL_GATE }}"
    assert 'if [[ $SKIP_FULL_GATE == true ]]; then' in step["run"]
    assert 'echo "reuse=true" >>"$GITHUB_OUTPUT"' in step["run"]
    assert ".github/scripts/find-nightly-gate.sh" in step["run"]
