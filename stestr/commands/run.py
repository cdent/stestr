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

"""Run a projects tests and load them into stestr."""

from math import ceil
import os
import subprocess
import sys

import six
import subunit
import testtools

from stestr.commands import load
from stestr import config_file
from stestr import output
from stestr.repository import abstract as repository
from stestr.repository import util
from stestr.testlist import parse_list


def set_cli_opts(parser):
    parser.add_argument("--failing", action="store_true",
                        default=False,
                        help="Run only tests known to be failing.")
    parser.add_argument("--serial", action="store_true",
                        default=False,
                        help="Run tests in a serial process.")
    parser.add_argument("--concurrency", action="store", default=0,
                        help="How many processes to use. The default (0) "
                             "autodetects your CPU count.")
    parser.add_argument("--load-list", default=None,
                        help="Only run tests listed in the named file."),
    parser.add_argument("--partial", action="store_true", default=False,
                        help="Only some tests will be run. Implied by "
                             "--failing.")
    parser.add_argument("--subunit", action="store_true", default=False,
                        help="Display results in subunit format.")
    parser.add_argument("--until-failure", action="store_true", default=False,
                        help="Repeat the run again and again until failure "
                             "occurs.")
    parser.add_argument("--analyze-isolation", action="store_true",
                        default=False,
                        help="Search the last test run for 2-test test "
                             "isolation interactions.")
    parser.add_argument("--isolated", action="store_true",
                        default=False,
                        help="Run each test id in a separate test runner.")
    parser.add_argument("--worker-file", action="store", default=None,
                        dest='worker_path',
                        help="Optional path of a manual worker grouping file "
                             "to use for the run")
    parser.add_argument('--blacklist-file', '-b',
                        default=None, dest='blacklist_file',
                        help='Path to a blacklist file, this file '
                             'contains a separate regex exclude on each '
                             'newline')
    parser.add_argument('--whitelist-file', '-w',
                        default=None, dest='whitelist_file',
                        help='Path to a whitelist file, this file '
                             'contains a separate regex on each newline.')
    parser.add_argument('--black-regex', '-B', default=None,
                        dest='black_regex',
                        help='Test rejection regex. If a test cases name '
                        'matches on re.search() operation , '
                        'it will be removed from the final test list. '
                        'Effectively the black-regexp is added to '
                        ' black regexp list, but you do need to edit a file. '
                        'The black filtering happens after the initial '
                        ' white selection, which by default is everything.')
    parser.add_argument('--no-discover', '-n', default=None, metavar='TEST_ID',
                        help="Takes in a single test to bypasses test discover"
                             " and just execute the test specified. A file "
                             "name may be used in place of a test name.")
    parser.add_argument('--random', '-r', action="store_true", default=False,
                        help="Randomize the test order after they are "
                             "partitioned into separate workers")
    parser.add_argument('--combine', action='store_true', default=False,
                        help="Combine the results from the test run with the "
                             "last run in the repository")
    parser.add_argument('--no-subunit-trace', action='store_true',
                        default=False,
                        help='Disable the default subunit-trace output filter')
    parser.add_argument('--color', action='store_true', default=False,
                        help='Enable color output in the subunit-trace output,'
                             ' if subunit-trace output is enabled. (this is '
                             'the default). If subunit-trace is disable this '
                             ' does nothing.')


def get_cli_help():
    help_str = "Run the tests for a project and load them into a repository."
    return help_str


def _find_failing(repo):
    run = repo.get_failing()
    case = run.get_test()
    ids = []

    def gather_errors(test_dict):
        if test_dict['status'] == 'fail':
            ids.append(test_dict['id'])

    result = testtools.StreamToDict(gather_errors)
    result.startTestRun()
    try:
        case.run(result)
    finally:
        result.stopTestRun()
    return ids


def run_command(config='.stestr.conf', repo_type='file',
                repo_url=None, test_path=None, top_dir=None, group_regex=None,
                failing=False, serial=False, concurrency=0, load_list=None,
                partial=False, subunit_out=False, until_failure=False,
                analyze_isolation=False, isolated=False, worker_path=None,
                blacklist_file=None, whitelist_file=None, black_regex=None,
                no_discover=False, random=False, combine=False, filters=None,
                pretty_out=True, color=False, stdout=sys.stdout):
    """Function to execute the run command

    This function implements the run command. It will run the tests specified
    in the parameters based on the provided config file and/or arguments
    specified in the way specified by the arguments. The results will be
    printed to STDOUT and loaded into the repository.

    :param str config: The path to the stestr config file. Must be a string.
    :param str repo_type: This is the type of repository to use. Valid choices
        are 'file' and 'sql'.
    :param str repo_url: The url of the repository to use.
    :param str test_path: Set the test path to use for unittest discovery.
        If both this and the corresponding config file option are set, this
        value will be used.
    :param str top_dir: The top dir to use for unittest discovery. This takes
        precedence over the value in the config file. (if one is present in
        the config file)
    :param str group_regex: Set a group regex to use for grouping tests
        together in the stestr scheduler. If both this and the corresponding
        config file option are set this value will be used.
    :param bool failing: Run only tests known to be failing.
    :param bool serial: Run tests serially
    :param int concurrency: "How many processes to use. The default (0)
        autodetects your CPU count and uses that.
    :param str load_list: The path to a list of test_ids. If specified only
        tests listed in the named file will be run.
    :param bool partial: Only some tests will be run. Implied by `--failing`.
    :param bool subunit_out: Display results in subunit format.
    :param bool until_failure: Repeat the run again and again until failure
        occurs.
    :param bool analyze_isolation: Search the last test run for 2-test test
        isolation interactions.
    :param bool isolated: Run each test id in a separate test runner.
    :param str worker_path: Optional path of a manual worker grouping file
        to use for the run.
    :param str blacklist_file: Path to a blacklist file, this file contains a
        separate regex exclude on each newline.
    :param str whitelist_file: Path to a whitelist file, this file contains a
        separate regex on each newline.
    :param str black_regex: Test rejection regex. If a test cases name matches
        on re.search() operation, it will be removed from the final test list.
    :param str no_discover: Takes in a single test_id to bypasses test
        discover and just execute the test specified. A file name may be used
        in place of a test name.
    :param bool random: Randomize the test order after they are partitioned
        into separate workers
    :param bool combine: Combine the results from the test run with the
        last run in the repository
    :param list filters: A list of string regex filters to initially apply on
        the test list. Tests that match any of the regexes will be used.
        (assuming any other filtering specified also uses it)
    :param bool pretty_out: Use the subunit-trace output filter
    :param bool color: Enable colorized output in subunit-trace
    :param file stdout: The file object to write all output to. By default this
        is sys.stdout

    :return return_code: The exit code for the command. 0 for success and > 0
        for failures.
    :rtype: int
    """
    try:
        repo = util.get_repo_open(repo_type, repo_url)
    # If a repo is not found, and there a testr config exists just create it
    except repository.RepositoryNotFound:
        if not os.path.isfile(config) and not test_path:
            msg = ("No config file found and --test-path not specified. "
                   "Either create or specify a .stestr.conf or use "
                   "--test-path ")
            stdout.write(msg)
            exit(1)
        repo = util.get_repo_initialise(repo_type, repo_url)
    combine_id = None
    if combine:
        latest_id = repo.latest_id()
        combine_id = six.text_type(latest_id)
    if no_discover:
        ids = no_discover
        if ids.find('/') != -1:
            root, _ = os.path.splitext(ids)
            ids = root.replace('/', '.')
        run_cmd = 'python -m subunit.run ' + ids

        def run_tests():
            run_proc = [('subunit', output.ReturnCodeToSubunit(
                subprocess.Popen(run_cmd, shell=True,
                                 stdout=subprocess.PIPE)))]
            return load.load(in_streams=run_proc,
                             partial=partial, subunit_out=subunit_out,
                             repo_type=repo_type,
                             repo_url=repo_url, run_id=combine_id,
                             pretty_out=pretty_out,
                             color=color, stdout=stdout)

        if not until_failure:
            return run_tests()
        else:
            while True:
                result = run_tests()
                # If we're using subunit output we want to make sure to check
                # the result from the repository because load() returns 0
                # always on subunit output
                if subunit:
                    summary = testtools.StreamSummary()
                    last_run = repo.get_latest_run().get_subunit_stream()
                    stream = subunit.ByteStreamToStreamResult(last_run)
                    summary.startTestRun()
                    try:
                        stream.run(summary)
                    finally:
                        summary.stopTestRun()
                    if not summary.wasSuccessful():
                        result = 1
                if result:
                    return result

    if failing or analyze_isolation:
        ids = _find_failing(repo)
    else:
        ids = None
    if load_list:
        list_ids = set()
        # Should perhaps be text.. currently does its own decode.
        with open(load_list, 'rb') as list_file:
            list_ids = set(parse_list(list_file.read()))
        if ids is None:
            # Use the supplied list verbatim
            ids = list_ids
        else:
            # We have some already limited set of ids, just reduce to ids
            # that are both failing and listed.
            ids = list_ids.intersection(ids)

    conf = config_file.TestrConf(config)
    if not analyze_isolation:
        cmd = conf.get_run_command(
            ids, regexes=filters, group_regex=group_regex, repo_type=repo_type,
            repo_url=repo_url, serial=serial, worker_path=worker_path,
            concurrency=concurrency, blacklist_file=blacklist_file,
            black_regex=black_regex, top_dir=top_dir, test_path=test_path,
            randomize=random)
        if isolated:
            result = 0
            cmd.setUp()
            try:
                ids = cmd.list_tests()
            finally:
                cmd.cleanUp()
            for test_id in ids:
                # TODO(mtreinish): add regex
                cmd = conf.get_run_command(
                    [test_id], filters, group_regex=group_regex,
                    repo_type=repo_type, repo_url=repo_url, serial=serial,
                    worker_path=worker_path, concurrency=concurrency,
                    blacklist_file=blacklist_file, black_regex=black_regex,
                    randomize=random, test_path=test_path, top_dir=top_dir)

                run_result = _run_tests(cmd, failing,
                                        analyze_isolation,
                                        isolated,
                                        until_failure,
                                        subunit_out=subunit_out,
                                        combine_id=combine_id,
                                        repo_type=repo_type,
                                        repo_url=repo_url,
                                        pretty_out=pretty_out,
                                        color=color,
                                        stdout=stdout)
                if run_result > result:
                    result = run_result
            return result
        else:
            return _run_tests(cmd, failing, analyze_isolation,
                              isolated, until_failure,
                              subunit_out=subunit_out,
                              combine_id=combine_id,
                              repo_type=repo_type,
                              repo_url=repo_url,
                              pretty_out=pretty_out,
                              color=color,
                              stdout=stdout)
    else:
        # Where do we source data about the cause of conflicts.
        # XXX: Should instead capture the run id in with the failing test
        # data so that we can deal with failures split across many partial
        # runs.
        latest_run = repo.get_latest_run()
        # Stage one: reduce the list of failing tests (possibly further
        # reduced by testfilters) to eliminate fails-on-own tests.
        spurious_failures = set()
        for test_id in ids:
            # TODO(mtrienish): Add regex
            cmd = conf.get_run_command(
                [test_id], group_regex=group_regex, repo_type=repo_type,
                repo_url=repo_url, serial=serial, worker_path=worker_path,
                concurrency=concurrency, blacklist_file=blacklist_file,
                black_regex=black_regex, randomize=random, test_path=test_path,
                top_dir=top_dir)
            if not _run_tests(cmd):
                # If the test was filtered, it won't have been run.
                if test_id in repo.get_test_ids(repo.latest_id()):
                    spurious_failures.add(test_id)
                # This is arguably ugly, why not just tell the system that
                # a pass here isn't a real pass? [so that when we find a
                # test that is spuriously failing, we don't forget
                # that it is actually failing.
                # Alternatively, perhaps this is a case for data mining:
                # when a test starts passing, keep a journal, and allow
                # digging back in time to see that it was a failure,
                # what it failed with etc...
                # The current solution is to just let it get marked as
                # a pass temporarily.
        if not spurious_failures:
            # All done.
            return 0
        # spurious-failure -> cause.
        test_conflicts = {}
        for spurious_failure in spurious_failures:
            candidate_causes = _prior_tests(
                latest_run, spurious_failure)
            bottom = 0
            top = len(candidate_causes)
            width = top - bottom
            while width:
                check_width = int(ceil(width / 2.0))
                # TODO(mtreinish): Add regex
                cmd = conf.get_run_command(
                    candidate_causes[bottom:bottom + check_width]
                    + [spurious_failure],
                    group_regex=group_regex, repo_type=repo_type,
                    repo_url=repo_url, serial=serial, worker_path=worker_path,
                    concurrency=concurrency, blacklist_file=blacklist_file,
                    black_regex=black_regex, randomize=random,
                    test_path=test_path, top_dir=top_dir)
                _run_tests(cmd)
                # check that the test we're probing still failed - still
                # awkward.
                found_fail = []

                def find_fail(test_dict):
                    if test_dict['id'] == spurious_failure:
                        found_fail.append(True)

                checker = testtools.StreamToDict(find_fail)
                checker.startTestRun()
                try:
                    repo.get_failing().get_test().run(checker)
                finally:
                    checker.stopTestRun()
                if found_fail:
                    # Our conflict is in bottom - clamp the range down.
                    top = bottom + check_width
                    if width == 1:
                        # found the cause
                        test_conflicts[
                            spurious_failure] = candidate_causes[bottom]
                        width = 0
                    else:
                        width = top - bottom
                else:
                    # Conflict in the range we did not run: discard bottom.
                    bottom = bottom + check_width
                    if width == 1:
                        # there will be no more to check, so we didn't
                        # reproduce the failure.
                        width = 0
                    else:
                        width = top - bottom
            if spurious_failure not in test_conflicts:
                # Could not determine cause
                test_conflicts[spurious_failure] = 'unknown - no conflicts'
        if test_conflicts:
            table = [('failing test', 'caused by test')]
            for failure, causes in test_conflicts.items():
                table.append((failure, causes))
            output.output_table(table)
            return 3
        return 0


def _prior_tests(self, run, failing_id):
    """Calculate what tests from the test run run ran before test_id.

    Tests that ran in a different worker are not included in the result.
    """
    if not getattr(self, '_worker_to_test', False):
        case = run.get_test()
        # Use None if there is no worker-N tag
        # If there are multiple, map them all.
        # (worker-N -> [testid, ...])
        worker_to_test = {}
        # (testid -> [workerN, ...])
        test_to_worker = {}

        def map_test(test_dict):
            tags = test_dict['tags']
            id = test_dict['id']
            workers = []
            for tag in tags:
                if tag.startswith('worker-'):
                    workers.append(tag)
            if not workers:
                workers = [None]
            for worker in workers:
                worker_to_test.setdefault(worker, []).append(id)
            test_to_worker.setdefault(id, []).extend(workers)

        mapper = testtools.StreamToDict(map_test)
        mapper.startTestRun()
        try:
            case.run(mapper)
        finally:
            mapper.stopTestRun()
        self._worker_to_test = worker_to_test
        self._test_to_worker = test_to_worker
    failing_workers = self._test_to_worker[failing_id]
    prior_tests = []
    for worker in failing_workers:
        worker_tests = self._worker_to_test[worker]
        prior_tests.extend(worker_tests[:worker_tests.index(failing_id)])
    return prior_tests


def _run_tests(cmd, failing, analyze_isolation, isolated, until_failure,
               subunit_out=False, combine_id=None, repo_type='file',
               repo_url=None, pretty_out=True, color=False, stdout=sys.stdout):
    """Run the tests cmd was parameterised with."""
    cmd.setUp()
    try:
        def run_tests():
            run_procs = [('subunit',
                          output.ReturnCodeToSubunit(
                              proc)) for proc in cmd.run_tests()]
            partial = False
            if (failing or analyze_isolation or isolated):
                partial = True
            if not run_procs:
                stdout.write("The specified regex doesn't match with anything")
                return 1
            return load.load((None, None), in_streams=run_procs,
                             partial=partial, subunit_out=subunit_out,
                             repo_type=repo_type,
                             repo_url=repo_url, run_id=combine_id,
                             pretty_out=pretty_out, color=color, stdout=stdout)

        if not until_failure:
            return run_tests()
        else:
            while True:
                result = run_tests()
                # If we're using subunit output we want to make sure to check
                # the result from the repository because load() returns 0
                # always on subunit output
                if subunit_out:
                    repo = util.get_repo_open(repo_type, repo_url)
                    summary = testtools.StreamSummary()
                    last_run = repo.get_latest_run().get_subunit_stream()
                    stream = subunit.ByteStreamToStreamResult(last_run)
                    summary.startTestRun()
                    try:
                        stream.run(summary)
                    finally:
                        summary.stopTestRun()
                    if not summary.wasSuccessful():
                        result = 1
                if result:
                    return result
    finally:
        cmd.cleanUp()


def run(arguments):
    filters = arguments[1] or None
    args = arguments[0]
    pretty_out = not args.no_subunit_trace

    return run_command(
        config=args.config, repo_type=args.repo_type, repo_url=args.repo_url,
        test_path=args.test_path, top_dir=args.top_dir,
        group_regex=args.group_regex, failing=args.failing, serial=args.serial,
        concurrency=args.concurrency, load_list=args.load_list,
        partial=args.partial, subunit_out=args.subunit,
        until_failure=args.until_failure,
        analyze_isolation=args.analyze_isolation, isolated=args.isolated,
        worker_path=args.worker_path, blacklist_file=args.blacklist_file,
        whitelist_file=args.whitelist_file, black_regex=args.black_regex,
        no_discover=args.no_discover, random=args.random, combine=args.combine,
        filters=filters, pretty_out=pretty_out, color=args.color)
