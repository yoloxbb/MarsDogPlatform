"""Regression coverage for derived Debian metadata relocation and tamper rejection."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import prepare_extended_ros as dependencies

class DependencyRelocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.payload = self.base / "deps"
        self.view = self.base / "relocated"
        self.payload.mkdir()
        for key, value in (("BASE", self.base), ("PREFIX", self.payload), ("VIEW", self.view)):
            context = patch.object(dependencies, key, value)
            context.start()
            self.addCleanup(context.stop)
        self.header = self.payload / "opt/ros/humble/include/example/api.hpp"
        self.header.parent.mkdir(parents=True)
        self.header.write_text("// original\n")
        self.config = self.payload / "usr/share/example/cmake/example.cmake"
        self.config.parent.mkdir(parents=True)

    def test_relocates_only_existing_absolute_payload_paths(self):
        text = '"/opt/ros/humble/include/example;/opt/ros/humble/include/system-only"'
        self.config.write_text(text)
        before = dependencies.inventory(self.payload)
        dependencies.relocate()
        actual = (self.view / self.config.relative_to(self.payload)).read_text()
        self.assertIn(str(self.view / "opt/ros/humble/include/example"), actual)
        self.assertIn("/opt/ros/humble/include/system-only", actual)
        self.assertEqual(before, dependencies.inventory(self.payload))

    def test_cmake_variable_relative_path_remains_relative(self):
        (self.payload / "lib/x86_64-linux-gnu").mkdir(parents=True)
        self.config.write_text('set(X "$' + '{PACKAGE_PREFIX_DIR}/lib/x86_64-linux-gnu")')
        dependencies.relocate()
        self.assertEqual(self.config.read_text(),
                         (self.view / self.config.relative_to(self.payload)).read_text())

    def test_existing_view_is_idempotent_and_rejects_changes(self):
        self.config.write_text('set(X "/opt/ros/humble/include/example")')
        dependencies.relocate()
        dependencies.relocate()
        (self.view / self.header.relative_to(self.payload)).write_text("// changed\n")
        with self.assertRaisesRegex(RuntimeError, "has changed"):
            dependencies.relocate()
        self.assertEqual(self.header.read_text(), "// original\n")

    def test_relative_library_symlink_is_preserved(self):
        target = self.payload / "usr/lib/libexample.so.1"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"binary-fixture")
        link = target.with_name("libexample.so")
        link.symlink_to(target.name)
        self.config.write_text('set(X "/usr/lib/libexample.so")')
        dependencies.relocate()
        self.assertEqual((self.view / link.relative_to(self.payload)).readlink(), Path(target.name))
        self.assertEqual((self.view / link.relative_to(self.payload)).read_bytes(), b"binary-fixture")


class VendorBuildCopyTests(unittest.TestCase):
    def test_generated_sql_stays_in_copy_and_other_edits_are_rejected(self):
        import check_extended_ros_build as build
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "sealed"
            resources = source / "rtabmap/corelib/src/resources"
            resources.mkdir(parents=True)
            (resources / "DatabaseSchema.sql.in").write_text("fixed template")
            with patch.object(build, "BASE", base / "out"):
                work = build.rtabmap_build_copy(source)
                generated = work / "rtabmap/corelib/src/resources/DatabaseSchema.sql"
                generated.write_text("configured SQL")
                self.assertEqual(build.rtabmap_build_copy(source), work)
                self.assertFalse((resources / "DatabaseSchema.sql").exists())
                (work / "rtabmap/corelib/src/resources/DatabaseSchema.sql.in").write_text("changed")
                with self.assertRaisesRegex(RuntimeError, "differs"):
                    build.rtabmap_build_copy(source)

    def test_polluted_sealed_snapshot_is_rejected(self):
        import check_extended_ros_build as build
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "sealed"
            resources = source / "rtabmap/corelib/src/resources"
            resources.mkdir(parents=True)
            (resources / "DatabaseSchema.sql").write_text("unrecorded")
            with patch.object(build, "BASE", base / "out"):
                with self.assertRaisesRegex(RuntimeError, "differs"):
                    build.rtabmap_build_copy(source)

if __name__ == "__main__":
    unittest.main()
