from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import json
import os
import shlex
import stat
import tempfile
import time
import unittest

import common_tests
import hierarchy_tests

from hh_paths import hh_client

from mini_state_test_driver import MiniStateTestDriver, MiniStateClassicTestDriver

def write_echo_json(f, obj):
    f.write("echo %s\n" % shlex.quote(json.dumps(obj)))


class LazyInitTestDriver(MiniStateTestDriver):
    def write_local_conf(self):
        with open(os.path.join(self.repo_dir, 'hh.conf'), 'w') as f:
            f.write(
                r"""
# some comment
use_mini_state = true
use_watchman = true
watchman_subscribe_v2 = true
lazy_decl = true
lazy_parse = true
lazy_init = true
incremental_init = true
enable_fuzzy_search = false
"""
            )


class LazyInitCommonTests(
    common_tests.CommonTests, LazyInitTestDriver, unittest.TestCase
):
    pass


class LazyInitHeirarchyTests(
    hierarchy_tests.HierarchyTests, LazyInitTestDriver, unittest.TestCase
):
    pass


class MiniStateCommonTests(
    common_tests.CommonTests, MiniStateTestDriver, unittest.TestCase
):
    pass


class MiniStateBarebonesTestsClassic(
    common_tests.BarebonesTests, MiniStateClassicTestDriver, unittest.TestCase
):
    pass


class MiniStateHierarchyTests(
    hierarchy_tests.HierarchyTests, MiniStateTestDriver, unittest.TestCase
):
    pass


class MiniStateTests(MiniStateTestDriver, unittest.TestCase):
    """
    Tests in this class are specific to saved state; would not make sense
    for them to run on a fresh init
    """
    template_repo = 'hphp/hack/test/integration/data/simple_repo'

    def test_hhconfig_change(self):
        """
        Start hh_server, then change .hhconfig and check that the server
        restarts itself
        """
        self.start_hh_server()
        self.check_cmd(['No errors!'])
        with open(os.path.join(self.repo_dir, '.hhconfig'), 'w') as f:
            f.write(
                r"""
# some comment
assume_php = true
""")

        # Server may take some time to kill itself.
        time.sleep(2)

        # this should start a new server
        self.check_cmd(['No errors!'])
        # check how the old one exited
        log_file = self.proc_call([
            hh_client, '--logname', self.repo_dir
        ])[0].strip() + '.old'
        with open(log_file) as f:
            logs = f.read()
            self.assertIn('.hhconfig changed in an incompatible way', logs)

    def test_watchman_timeout(self):
        with open(os.path.join(self.repo_dir, 'hh.conf'), 'a') as f:
            f.write(r"""
watchman_init_timeout = 1
""")

        with open(os.path.join(self.bin_dir, 'watchman'), 'w') as f:
            f.write(r"""sleep 2""")
            os.fchmod(f.fileno(), stat.S_IRWXU)

        self.run_check()
        # Stop the server, ensuring that its logs get flushed
        self.proc_call([hh_client, 'stop', self.repo_dir])
        self.assertIn('Watchman_sig.Types.Timeout', self.get_server_logs())

    def test_incrementally_generated_saved_state(self):
        def dump_saved_state(obj):
            saved_state_path = os.path.join(tempfile.mkdtemp(), 'new_saved_state')
            obj.save_command(obj.repo_dir, saved_state_path=saved_state_path)
            return saved_state_path
        def add_file_that_depends_on_class_a(filename):
            with open(filename, 'w') as f:
                f.write("""<?hh // strict

class UsesAToo {
  public function test() : int {
    return A::foo();
  }

}
                """)
        def change_return_type_on_base_class(filename):
            # Change the return type from into to string
            with open(filename, 'w') as f:
                f.write("""<?hh // strict

class B {

  public static function foo () : string {
      return "hello";
  }
}
                """)
        old_saved_state = dump_saved_state(self)
        new_file = os.path.join(self.repo_dir, 'class_3b.php')
        add_file_that_depends_on_class_a(new_file)
        self.check_cmd(['No errors!'], assert_loaded_mini_state=False)
        new_saved_state = dump_saved_state(self)
        change_return_type_on_base_class(os.path.join(self.repo_dir, 'class_1.php'))
        self.check_cmd([
            '{root}class_3.php:5:12,19: Invalid return type (Typing[4110])',
            '  {root}class_3.php:4:28,30: This is an int',
            '  {root}class_1.php:5:35,40: It is incompatible with a string',
            '{root}class_3b.php:5:12,19: Invalid return type (Typing[4110])',
            '  {root}class_3b.php:4:28,30: This is an int',
            '  {root}class_1.php:5:35,40: It is incompatible with a string',
        ], assert_loaded_mini_state=False)
        self.proc_call([hh_client, 'stop', self.repo_dir])
        # Start server with the original saved state. Will be missing the
        # second error because of the missing edge.
        self.start_hh_server(changed_files=['class_1.php'], saved_state_path=old_saved_state)
        self.check_cmd([
            '{root}class_3.php:5:12,19: Invalid return type (Typing[4110])',
            '  {root}class_3.php:4:28,30: This is an int',
            '  {root}class_1.php:5:35,40: It is incompatible with a string',
        ])
        self.proc_call([hh_client, 'stop', self.repo_dir])
        # Start another server with the new saved state. Will have both errors.
        self.start_hh_server(changed_files=['class_1.php'], saved_state_path=new_saved_state)
        self.check_cmd([
            '{root}class_3.php:5:12,19: Invalid return type (Typing[4110])',
            '  {root}class_3.php:4:28,30: This is an int',
            '  {root}class_1.php:5:35,40: It is incompatible with a string',
            '{root}class_3b.php:5:12,19: Invalid return type (Typing[4110])',
            '  {root}class_3b.php:4:28,30: This is an int',
            '  {root}class_1.php:5:35,40: It is incompatible with a string',
        ])
