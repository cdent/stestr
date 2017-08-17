# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import io
import operator
import os

import mock
import six
import subunit
import testtools

from stestr import bisect_tests
from stestr.tests import base


class FakeTestRunTags(object):

    def __init__(self, failure=True):
        sample_stream_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'sample_streams')
        failure_path = os.path.join(sample_stream_path, 'failure.subunit')
        success_path = os.path.join(sample_stream_path, 'successful.subunit')
        if failure:
            with open(failure_path, 'rb') as fd:
                self._content = six.binary_type(fd.read())
        else:
            with open(success_path, 'rb') as fd:
                self._content = six.binary_type(fd.read())

    def get_test(self):
        content = io.BytesIO()
        case = subunit.ByteStreamToStreamResult(io.BytesIO(self._content),
                                                non_subunit_name='stdout')
        result = testtools.StreamToExtendedDecorator(
            subunit.TestProtocolClient(content))
        result = testtools.StreamResultRouter(result)
        cat = subunit.test_results.CatFiles(content)
        result.add_rule(cat, 'test_id', test_id=None)
        result.startTestRun()
        case.run(result)
        result.stopTestRun()
#        content.seek(0)
        case = subunit.ProtocolTestCase(content)

        def wrap_result(result):
            # Wrap in a router to mask out startTestRun/stopTestRun from the
            # ExtendedToStreamDecorator.
            result = testtools.StreamResultRouter(
                result, do_start_stop_run=False)
            # Wrap that in ExtendedToStreamDecorator to convert v1 calls to
            # StreamResult.
            return testtools.ExtendedToStreamDecorator(result)
        return testtools.DecorateTestCaseResult(
            case, wrap_result, operator.methodcaller('startTestRun'),
            operator.methodcaller('stopTestRun'))


class TestBisectTests(base.TestCase):
    def setUp(self):
        super(TestBisectTests, self).setUp()
        self.repo_mock = mock.create_autospec(
            'stestr.repository.file.Repository')
        self.conf_mock = mock.create_autospec('stestr.config_file.TestrConf')
        self.run_func_mock = mock.MagicMock()
        self.latest_run_mock = mock.MagicMock()

    def test_bisect_no_failures_provided(self):
        bisector = bisect_tests.IsolationAnalyzer(
            self.latest_run_mock, self.conf_mock, self.run_func_mock,
            self.repo_mock)
        self.assertRaises(ValueError, bisector.bisect_tests, [])

    def test_prior_tests_invlaid_test_id(self):
        bisector = bisect_tests.IsolationAnalyzer(
            self.latest_run_mock, self.conf_mock, self.run_func_mock,
            self.repo_mock)
        run = FakeTestRunTags()
        self.assertRaises(KeyError, bisector._prior_tests, run, 'bad_test_id')

    def test_get_prior_tests(self):
        bisector = bisect_tests.IsolationAnalyzer(
            self.latest_run_mock, self.conf_mock, self.run_func_mock,
            self.repo_mock)
        run = FakeTestRunTags()
        prior_tests = bisector._prior_tests(
            run,
            'stestr.tests.test_subunit_trace.TestSubunitTrace.'
            'test_trace_with_all_skips')
        self.assertEqual(['test_that_passed'], prior_tests)
