# SPDX-License-Identifier: MIT
"""Catalog validation, rendering, and contribution-flow regression tests."""

from copy import deepcopy
from datetime import date, timedelta
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import catalog


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "data/projects").mkdir(parents=True)
        shutil.copy(catalog.ROOT / "data/taxonomy.json", self.root / "data/taxonomy.json")
        self.project = catalog.read_json(catalog.ROOT / "examples/project.json")
        self.project["last_reviewed"] = date.today().isoformat()
        self.save()
        self.readme = f"# Fixture\n\nManual introduction.\n\n{catalog.START}\n\nOld catalog.\n\n{catalog.END}\n\nManual footer.\n"
        (self.root / "README.md").write_text(self.readme, encoding="utf-8")

    def save(self, project=None):
        project = self.project if project is None else project
        path = self.root / "data/projects" / (project["id"] + ".json")
        path.write_text(json.dumps(project), encoding="utf-8")
        return path

    def load(self):
        return catalog.load_catalog(self.root)

    def assert_invalid(self, message):
        with self.assertRaisesRegex(catalog.CatalogError, message):
            self.load()

    def cli(self, *args):
        output = io.StringIO()
        with patch.object(catalog, "ROOT", self.root), patch("sys.argv", ["catalog.py", *args]), \
                patch("sys.stdout", output), patch("sys.stderr", output):
            result = catalog.main()
        return result, output.getvalue()

    def test_example_is_valid(self):
        _, projects = self.load()
        self.assertEqual(projects, [self.project])

    def test_seed_catalog_and_readme_are_valid(self):
        taxonomy, projects = catalog.load_catalog()
        self.assertEqual(len(projects), len(list((catalog.ROOT / "data/projects").glob("*.json"))))
        self.assertEqual(catalog.render_readme(catalog.ROOT, taxonomy, projects),
                         (catalog.ROOT / "README.md").read_text(encoding="utf-8"))

    def test_missing_and_misspelled_fields_fail(self):
        misspelled = "description".replace("tion", "ton")
        self.project[misspelled] = self.project.pop("description")
        self.save()
        self.assert_invalid(f"missing fields.*description.*unexpected fields.*{misspelled}")

    def test_unknown_taxonomy_values_fail(self):
        for field, value in [("category", "invented"), ("local_mode", "offline"),
                             ("use_cases", ["unknown"]), ("platforms", ["os2"]),
                             ("hardware", ["everything"])]:
            with self.subTest(field=field):
                changed = deepcopy(self.project)
                changed[field] = value
                self.save(changed)
                self.assert_invalid("unknown")

    def test_non_objects_fail_without_tracebacks(self):
        for value in [None, [], "entry", True]:
            with self.subTest(value=value):
                path = self.root / "data/projects/example-project.json"
                path.write_text(json.dumps(value), encoding="utf-8")
                self.assert_invalid("entry must be an object")

    def test_bad_field_types_fail(self):
        for field, value in [("name", []), ("category", []), ("use_cases", "serve-models"),
                             ("hardware", [{}]), ("compatibility", [False]),
                             ("license", []), ("sources", {}), ("last_reviewed", None)]:
            with self.subTest(field=field):
                changed = deepcopy(self.project)
                changed[field] = value
                self.save(changed)
                self.assert_invalid("must")

    def test_empty_use_cases_and_sources_fail(self):
        for field in ["use_cases", "sources"]:
            with self.subTest(field=field):
                changed = deepcopy(self.project)
                changed[field] = []
                self.save(changed)
                self.assert_invalid("nonempty|must not be empty")

    def test_duplicate_array_values_fail(self):
        self.project["use_cases"] *= 2
        self.save()
        self.assert_invalid("contains duplicates")

    def test_duplicate_json_keys_fail(self):
        path = self.root / "data/projects/example-project.json"
        path.write_text('{"id":"one","id":"two"}', encoding="utf-8")
        self.assert_invalid("duplicate JSON key")

    def test_invalid_ids_and_filename_mismatch_fail(self):
        for identifier in ["MixedCase", "path/to/file", "valid-but-different"]:
            with self.subTest(identifier=identifier):
                changed = deepcopy(self.project)
                changed["id"] = identifier
                path = self.root / "data/projects/example-project.json"
                path.write_text(json.dumps(changed), encoding="utf-8")
                self.assert_invalid("id must|filename must")

    def test_repository_must_be_canonical(self):
        for repository in ["https://github.com/example/project/", "https://github.com/example/project.git",
                           "https://github.com/example/project#readme", "https://gitlab.com/example/project",
                           "https://github.com/example/project?x=y"]:
            with self.subTest(repository=repository):
                self.project["repository"] = repository
                self.save()
                self.assert_invalid("repository must")

    def test_unsafe_source_urls_fail(self):
        for value in ["http://example.com", "javascript:alert(1)", "https://user:password@example.com",
                      "https://example.com:8443", "https://localhost/readme", "https://example.com/x y",
                      "https://example.com/)bad", "https://example.com/<script>", "https://[bad"]:
            with self.subTest(url=value):
                self.project["sources"][0]["url"] = value
                self.save()
                self.assert_invalid("source.url")

    def test_oversized_and_multiline_descriptions_fail(self):
        for description in ["a" * 181, "first\nsecond", "first\tsecond", " padded ", ""]:
            with self.subTest(description=description):
                self.project["description"] = description
                self.save()
                self.assert_invalid("description")

    def test_invalid_and_future_dates_fail(self):
        for reviewed in ["20260101", "2026-02-30", "2026-1-1", (date.today() + timedelta(days=1)).isoformat()]:
            with self.subTest(reviewed=reviewed):
                self.project["last_reviewed"] = reviewed
                self.save()
                self.assert_invalid("last_reviewed")

    def test_unknown_license_needs_visible_note(self):
        self.project["license"]["spdx"] = None
        self.project["limitations"] = []
        self.save()
        self.assert_invalid("unknown licensing")
        self.project["limitations"] = ["Upstream licensing is unclear; confirm before redistribution."]
        self.save()
        taxonomy, projects = self.load()
        self.assertIn("Unclear; check upstream", catalog.catalog_markdown(taxonomy, projects))

    def test_spdx_expression_and_invalid_shape(self):
        self.project["license"]["spdx"] = "MIT OR Apache-2.0"
        self.save()
        self.load()
        self.project["license"]["spdx"] = "a license maybe"
        self.save()
        self.assert_invalid("SPDX")

    def test_cloud_entry_needs_limitations(self):
        self.project["local_mode"] = "cloud-dependent"
        self.project["limitations"] = []
        self.save()
        self.assert_invalid("cloud integrations must explain")

    def test_source_shape_and_duplicates_fail(self):
        self.project["sources"][0]["claim"] = "unexpected"
        self.save()
        self.assert_invalid("each source must contain")
        self.project["sources"][0].pop("claim")
        self.project["sources"] *= 2
        self.save()
        self.assert_invalid("duplicate URLs")

    def test_duplicate_names_and_repositories_are_case_insensitive(self):
        for field in ["name", "repository"]:
            with self.subTest(field=field):
                changed = deepcopy(self.project)
                changed["id"] = "another-project"
                changed["name"] = "Another Project"
                changed["repository"] = "https://github.com/another/project"
                changed[field] = self.project[field].upper() if field == "name" else "https://github.com/EXAMPLE/PROJECT"
                self.save(changed)
                self.assert_invalid(f"duplicate {field}")

    def test_empty_catalog_fails(self):
        (self.root / "data/projects/example-project.json").unlink()
        self.assert_invalid("at least one")

    def test_invalid_taxonomy_fails(self):
        path = self.root / "data/taxonomy.json"
        taxonomy = catalog.read_json(path)
        taxonomy["categories"] = []
        path.write_text(json.dumps(taxonomy), encoding="utf-8")
        self.assert_invalid("categories must be")

    def test_render_is_idempotent_and_preserves_manual_sections(self):
        taxonomy, projects = self.load()
        first = catalog.render_readme(self.root, taxonomy, projects)
        self.assertTrue(first.startswith(self.readme.split(catalog.START)[0]))
        self.assertTrue(first.endswith(self.readme.split(catalog.END)[1]))
        (self.root / "README.md").write_text(first, encoding="utf-8")
        self.assertEqual(catalog.render_readme(self.root, taxonomy, projects), first)

    def test_bad_readme_markers_fail(self):
        taxonomy, projects = self.load()
        for readme in ["no markers", catalog.START + catalog.START + catalog.END,
                       catalog.END + catalog.START]:
            with self.subTest(readme=readme):
                (self.root / "README.md").write_text(readme, encoding="utf-8")
                with self.assertRaises(catalog.CatalogError):
                    catalog.render_readme(self.root, taxonomy, projects)

    def test_cloud_entries_only_appear_in_cloud_section_and_task_index(self):
        self.project["local_mode"] = "cloud-dependent"
        self.save()
        taxonomy, projects = self.load()
        generated = catalog.catalog_markdown(taxonomy, projects)
        core = generated.split("## Browse by category", 1)[1].split("## Cloud integrations", 1)[0]
        self.assertNotIn(self.project["repository"], core)
        self.assertIn(self.project["repository"], generated.split("## Cloud integrations", 1)[1])
        self.assertIn(catalog.project_link(self.project) + " (cloud)", generated)

    def test_unknown_hardware_and_markdown_escaping(self):
        self.project["name"] = "Example [name] | <tag>"
        self.save()
        taxonomy, projects = self.load()
        generated = catalog.catalog_markdown(taxonomy, projects)
        self.assertIn("Hardware: Not recorded", generated)
        self.assertIn(r"Example \[name\] \| \<tag\>", generated)

    def test_url_output_is_deduplicated_and_sorted(self):
        _, projects = self.load()
        urls = catalog.catalog_urls(projects * 2)
        self.assertEqual(urls, sorted(set(urls)))
        self.assertIn(self.project["license"]["url"], urls)
        self.assertIn(self.project["sources"][0]["url"], urls)

    def test_submission_flow_and_stale_readme_failure(self):
        self.assertEqual(self.cli("validate")[0], 0)
        result, message = self.cli("check")
        self.assertEqual(result, 1)
        self.assertIn("README is stale", message)
        self.assertEqual(self.cli("render")[0], 0)
        self.assertEqual(self.cli("check")[0], 0)
        result, urls = self.cli("links")
        self.assertEqual(result, 0)
        self.assertIn(self.project["repository"], urls)

    def test_changed_project_filter_rejects_invalid_ref(self):
        for ref in ["main", "--help", "a" * 39]:
            with self.subTest(ref=ref), self.assertRaisesRegex(catalog.CatalogError, "full commit SHA"):
                catalog.changed_projects(self.root, [self.project], ref)

    @unittest.skipUnless(shutil.which("git"), "Git is needed for changed-record integration test")
    def test_changed_project_filter_with_real_git_commits(self):
        def git(*args):
            return subprocess.run(["git", *args], cwd=self.root, check=True,
                                  capture_output=True, text=True).stdout.strip()

        git("init", "-q")
        git("add", ".")
        git("-c", "user.name=Catalog Tests", "-c", "user.email=catalog@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
        base = git("rev-parse", "HEAD")
        self.assertEqual(catalog.changed_projects(self.root, [self.project], base), [])
        self.project["description"] = "Updated fixture."
        self.save()
        git("add", ".")
        git("-c", "user.name=Catalog Tests", "-c", "user.email=catalog@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "-qm", "update")
        self.assertEqual(catalog.changed_projects(self.root, [self.project], base), [self.project])


if __name__ == "__main__":
    unittest.main()
