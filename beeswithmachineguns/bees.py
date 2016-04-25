#!/bin/env python

"""
The MIT License

Copyright (c) 2010 The Chicago Tribune & Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""

from multiprocessing import Pool
import os
import re
import socket
import time
import sys
IS_PY2 = sys.version_info.major == 2
if IS_PY2:
    from urllib2 import urlopen, Request
    from StringIO import StringIO
else:
    from urllib.request import urlopen, Request
    from io import StringIO
import base64
import csv
import random
import ssl
from contextlib import contextmanager
import traceback

import boto.ec2
import boto.exception
import paramiko
import json
from collections import defaultdict
import time
from sets import Set

STATE_FILENAME = os.path.expanduser('~/.bees')

# Utilities

@contextmanager
def _redirect_stdout(outfile=None):
    save_stdout = sys.stdout
    sys.stdout = outfile or StringIO()
    yield
    sys.stdout = save_stdout

def _read_server_list(*mr_zone):
    instance_ids = []
    if len(mr_zone) > 0:
        MR_STATE_FILENAME = _get_new_state_file_name(mr_zone[-1])
    else:
        MR_STATE_FILENAME = STATE_FILENAME
    if not os.path.isfile(MR_STATE_FILENAME):
        return (None, None, None, None)

    with open(MR_STATE_FILENAME, 'r') as f:
        username = f.readline().strip()
        key_name = f.readline().strip()
        zone = f.readline().strip()
        text = f.read()
        instance_ids = [i for i in text.split('\n') if i != '']

        print('Read {} bees from the roster: {}').format(len(instance_ids), zone)

    return (username, key_name, zone, instance_ids)

def _write_server_list(username, key_name, zone, instances):
    with open(_get_new_state_file_name(zone), 'w') as f:
        f.write('%s\n' % username)
        f.write('%s\n' % key_name)
        f.write('%s\n' % zone)
        f.write('\n'.join([instance.id for instance in instances]))

def _delete_server_list(zone):
    os.remove(_get_new_state_file_name(zone))


def _get_pem_path(key):
    return os.path.expanduser('~/.ssh/%s.pem' % key)

def _get_region(zone):
    return zone if 'gov' in zone else zone[:-1] # chop off the "d" in the "us-east-1d" to get the "Region"

def _get_security_group_id(connection, security_group_name, subnet):
    if not security_group_name:
        print('The bees need a security group to run under. Need to open a port from where you are to the target subnet.')
        return

    security_groups = connection.get_all_security_groups(filters={'group-name': [security_group_name]})

    if not security_groups:
        print('The bees need a security group to run under. The one specified was not found.')
        return

    group = security_groups[0] if security_groups else None

    return group.id

# Methods

def up(count, group, zone, image_id, instance_type, username, key_name, subnet, bid = None):
    """
    Startup the load testing server.
    """

    existing_username, existing_key_name, existing_zone, instance_ids = _read_server_list(zone)

    count = int(count)
    if existing_username == username and existing_key_name == key_name and existing_zone == zone:
        ec2_connection = boto.ec2.connect_to_region(_get_region(zone))
        existing_reservations = ec2_connection.get_all_instances(instance_ids=instance_ids)
        existing_instances = filter(lambda i: i.state == 'running', [r.instances[0] for r in existing_reservations])
        # User, key and zone match existing values and instance ids are found on state file
        if count <= len(existing_instances):
            # Count is less than the amount of existing instances. No need to create new ones.
            print('Bees are already assembled and awaiting orders.')
            return
        else:
            # Count is greater than the amount of existing instances. Need to create the only the extra instances.
            count -= len(existing_instances)
    elif instance_ids:
        # Instances found on state file but user, key and/or zone not matching existing value.
        # State file only stores one user/key/zone config combination so instances are unusable.
        print('Taking down {} unusable bees.'.format(len(instance_ids)))
        # Redirect prints in down() to devnull to avoid duplicate messages
        with _redirect_stdout():
            down()
        # down() deletes existing state file so _read_server_list() returns a blank state
        existing_username, existing_key_name, existing_zone, instance_ids = _read_server_list(zone)

    pem_path = _get_pem_path(key_name)

    if not os.path.isfile(pem_path):
        print('Warning. No key file found for %s. You will need to add this key to your SSH agent to connect.' % pem_path)

    print('Connecting to the hive.')

    try:
        ec2_connection = boto.ec2.connect_to_region(_get_region(zone))
    except boto.exception.NoAuthHandlerFound as e:
        print("Authenciation config error, perhaps you do not have a ~/.boto file with correct permissions?")
        print(e.message)
        return e
    except Exception as e:
        print("Unknown error occured:")
        print(e.message)
        return e

    if ec2_connection == None:
        raise Exception("Invalid zone specified? Unable to connect to region using zone name")

    groupId = group if subnet is None else _get_security_group_id(ec2_connection, group, subnet)
    print("GroupId found: %s" % groupId)

    placement = None if 'gov' in zone else zone
    print("Placement: %s" % placement)

    if bid:
        print('Attempting to call up %i spot bees, this can take a while...' % count)

        spot_requests = ec2_connection.request_spot_instances(
            image_id=image_id,
            price=bid,
            count=count,
            key_name=key_name,
            security_group_ids=[groupId],
            instance_type=instance_type,
            placement=placement,
            subnet_id=subnet)

        # it can take a few seconds before the spot requests are fully processed
        time.sleep(5)

        instances = _wait_for_spot_request_fulfillment(ec2_connection, spot_requests)
    else:
        print('Attempting to call up %i bees.' % count)

        try:
            reservation = ec2_connection.run_instances(
                image_id=image_id,
                min_count=count,
                max_count=count,
                key_name=key_name,
                security_group_ids=[groupId],
                instance_type=instance_type,
                placement=placement,
                subnet_id=subnet)

        except boto.exception.EC2ResponseError as e:
            print("Unable to call bees:", e.message)
            print("Is your sec group available in this region?")
            return e

        instances = reservation.instances

    if instance_ids:
        existing_reservations = ec2_connection.get_all_instances(instance_ids=instance_ids)
        existing_instances = filter(lambda i: i.state == 'running', [r.instances[0] for r in existing_reservations])
        map(instances.append, existing_instances)
        dead_instances = filter(lambda i: i not in [j.id for j in existing_instances], instance_ids)
        map(instance_ids.pop, [instance_ids.index(i) for i in dead_instances])

    print('Waiting for bees to load their machine guns...')

    instance_ids = instance_ids or []

    for instance in [i for i in instances if i.state == 'pending']:
        instance.update()
        while instance.state != 'running':
            print('.')
            time.sleep(5)
            instance.update()

        instance_ids.append(instance.id)

        print('Bee %s is ready for the attack.' % instance.id)

    ec2_connection.create_tags(instance_ids, { "Name": "a bee!" })

    _write_server_list(username, key_name, zone, instances)

    print('The swarm has assembled %i bees.' % len(instances))

def report():
    """
    Report the status of the load testing servers.
    """
    def _check_instances():
        '''helper function to check multiple region files ~/.bees.*'''
        if not instance_ids:
            print('No bees have been mobilized.')
            return

        ec2_connection = boto.ec2.connect_to_region(_get_region(zone))

        reservations = ec2_connection.get_all_instances(instance_ids=instance_ids)

        instances = []

        for reservation in reservations:
            instances.extend(reservation.instances)

        for instance in instances:
            print('Bee %s: %s @ %s' % (instance.id, instance.state, instance.ip_address))

    for i in _get_existing_regions():
        username, key_name, zone, instance_ids = _read_server_list(i)
        _check_instances()

def down(*mr_zone):
    """
    Shutdown the load testing server.
    """
    def _check_to_down_it():
        '''check if we can bring down some bees'''
        username, key_name, zone, instance_ids = _read_server_list(region)

        if not instance_ids:
            print('No bees have been mobilized.')
            return

        print('Connecting to the hive.')

        ec2_connection = boto.ec2.connect_to_region(_get_region(zone))

        print('Calling off the swarm for {}.').format(region)

        terminated_instance_ids = ec2_connection.terminate_instances(
            instance_ids=instance_ids)

        print('Stood down %i bees.' % len(terminated_instance_ids))

        _delete_server_list(zone)


    if len(mr_zone) > 0:
        username, key_name, zone, instance_ids = _read_server_list(mr_zone[-1])
    else:
        for region in _get_existing_regions():
            _check_to_down_it()

def _wait_for_spot_request_fulfillment(conn, requests, fulfilled_requests = []):
    """
    Wait until all spot requests are fulfilled.

    Once all spot requests are fulfilled, return a list of corresponding spot instances.
    """
    if len(requests) == 0:
        reservations = conn.get_all_instances(instance_ids = [r.instance_id for r in fulfilled_requests])
        return [r.instances[0] for r in reservations]
    else:
        time.sleep(10)
        print('.')

    requests = conn.get_all_spot_instance_requests(request_ids=[req.id for req in requests])
    for req in requests:
        if req.status.code == 'fulfilled':
            fulfilled_requests.append(req)
            print("spot bee `{}` joined the swarm.".format(req.instance_id))

    return _wait_for_spot_request_fulfillment(conn, [r for r in requests if r not in fulfilled_requests], fulfilled_requests)

def _attack(params):
    """
    Test the target URL with requests.

    Intended for use with multiprocessing.
    """
    print('Bee %i is joining the swarm.' % params['i'])

    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        pem_path = params.get('key_name') and _get_pem_path(params['key_name']) or None
        if not os.path.isfile(pem_path):
            client.load_system_host_keys()
            client.connect(params['instance_name'], username=params['username'])
        else:
            client.connect(
                params['instance_name'],
                username=params['username'],
                key_filename=pem_path)

        print('Bee %i is firing her machine gun. Bang bang!' % params['i'])

        options = ''
        if params['headers'] is not '':
            for h in params['headers'].split(';'):
                if h != '':
                    options += ' -H "%s"' % h.strip()

        if params['contenttype'] is not '':
            options += ' -T %s' % params['contenttype']

        stdin, stdout, stderr = client.exec_command('mktemp')
        # paramiko's read() returns bytes which need to be converted back to a str
        params['csv_filename'] = IS_PY2 and stdout.read().strip() or stdout.read().decode('utf-8').strip()
        if params['csv_filename']:
            options += ' -e %(csv_filename)s' % params
        else:
            print('Bee %i lost sight of the target (connection timed out creating csv_filename).' % params['i'])
            return None

        if params['post_file']:
            pem_file_path=_get_pem_path(params['key_name'])
            scpCommand = "scp -q -o 'StrictHostKeyChecking=no' -i %s %s %s@%s:~/" % (pem_file_path, params['post_file'], params['username'], params['instance_name'])
            os.system(scpCommand)
            options += ' -p ~/%s' % params['post_file']

        if params['keep_alive']:
            options += ' -k'

        if params['cookies'] is not '':
            options += ' -H \"Cookie: %s;sessionid=NotARealSessionID;\"' % params['cookies']
        else:
            options += ' -C \"sessionid=NotARealSessionID\"'

        if params['basic_auth'] is not '':
            options += ' -A %s' % params['basic_auth']

        params['options'] = options
        benchmark_command = 'ab -v 3 -r -n %(num_requests)s -c %(concurrent_requests)s %(options)s "%(url)s"' % params
        print(benchmark_command)
        stdin, stdout, stderr = client.exec_command(benchmark_command)

        response = {}

        # paramiko's read() returns bytes which need to be converted back to a str
        ab_results = IS_PY2 and stdout.read() or stdout.read().decode('utf-8')
        ms_per_request_search = re.search('Time\ per\ request:\s+([0-9.]+)\ \[ms\]\ \(mean\)', ab_results)

        if not ms_per_request_search:
            print('Bee %i lost sight of the target (connection timed out running ab).' % params['i'])
            return None

        requests_per_second_search = re.search('Requests\ per\ second:\s+([0-9.]+)\ \[#\/sec\]\ \(mean\)', ab_results)
        failed_requests = re.search('Failed\ requests:\s+([0-9.]+)', ab_results)
        response['failed_requests_connect'] = 0
        response['failed_requests_receive'] = 0
        response['failed_requests_length'] = 0
        response['failed_requests_exceptions'] = 0
        if float(failed_requests.group(1)) > 0:
            failed_requests_detail = re.search('(Connect: [0-9.]+, Receive: [0-9.]+, Length: [0-9.]+, Exceptions: [0-9.]+)', ab_results)
            if failed_requests_detail:
                response['failed_requests_connect'] = float(re.search('Connect:\s+([0-9.]+)', failed_requests_detail.group(0)).group(1))
                response['failed_requests_receive'] = float(re.search('Receive:\s+([0-9.]+)', failed_requests_detail.group(0)).group(1))
                response['failed_requests_length'] = float(re.search('Length:\s+([0-9.]+)', failed_requests_detail.group(0)).group(1))
                response['failed_requests_exceptions'] = float(re.search('Exceptions:\s+([0-9.]+)', failed_requests_detail.group(0)).group(1))

        complete_requests_search = re.search('Complete\ requests:\s+([0-9]+)', ab_results)

        response['number_of_200s'] = len(re.findall('HTTP/1.1\ 2[0-9][0-9]', ab_results))
        response['number_of_300s'] = len(re.findall('HTTP/1.1\ 3[0-9][0-9]', ab_results))
        response['number_of_400s'] = len(re.findall('HTTP/1.1\ 4[0-9][0-9]', ab_results))
        response['number_of_500s'] = len(re.findall('HTTP/1.1\ 5[0-9][0-9]', ab_results))

        response['ms_per_request'] = float(ms_per_request_search.group(1))
        response['requests_per_second'] = float(requests_per_second_search.group(1))
        response['failed_requests'] = float(failed_requests.group(1))
        response['complete_requests'] = float(complete_requests_search.group(1))

        stdin, stdout, stderr = client.exec_command('cat %(csv_filename)s' % params)
        response['request_time_cdf'] = []
        for row in csv.DictReader(stdout):
            row["Time in ms"] = float(row["Time in ms"])
            response['request_time_cdf'].append(row)
        if not response['request_time_cdf']:
            print('Bee %i lost sight of the target (connection timed out reading csv).' % params['i'])
            return None

        print('Bee %i is out of ammo.' % params['i'])

        client.close()

        return response
    except socket.error as e:
        return e
    except Exception as e:
        traceback.print_exc()
        print()
        raise e


def _summarize_results(results, params, csv_filename):
    summarized_results = dict()
    summarized_results['timeout_bees'] = [r for r in results if r is None]
    summarized_results['exception_bees'] = [r for r in results if type(r) == socket.error]
    summarized_results['complete_bees'] = [r for r in results if r is not None and type(r) != socket.error]
    summarized_results['timeout_bees_params'] = [p for r, p in zip(results, params) if r is None]
    summarized_results['exception_bees_params'] = [p for r, p in zip(results, params) if type(r) == socket.error]
    summarized_results['complete_bees_params'] = [p for r, p in zip(results, params) if r is not None and type(r) != socket.error]
    summarized_results['num_timeout_bees'] = len(summarized_results['timeout_bees'])
    summarized_results['num_exception_bees'] = len(summarized_results['exception_bees'])
    summarized_results['num_complete_bees'] = len(summarized_results['complete_bees'])

    complete_results = [r['complete_requests'] for r in summarized_results['complete_bees']]
    summarized_results['total_complete_requests'] = sum(complete_results)

    complete_results = [r['failed_requests'] for r in summarized_results['complete_bees']]
    summarized_results['total_failed_requests'] = sum(complete_results)

    complete_results = [r['failed_requests_connect'] for r in summarized_results['complete_bees']]
    summarized_results['total_failed_requests_connect'] = sum(complete_results)

    complete_results = [r['failed_requests_receive'] for r in summarized_results['complete_bees']]
    summarized_results['total_failed_requests_receive'] = sum(complete_results)

    complete_results = [r['failed_requests_length'] for r in summarized_results['complete_bees']]
    summarized_results['total_failed_requests_length'] = sum(complete_results)

    complete_results = [r['failed_requests_exceptions'] for r in summarized_results['complete_bees']]
    summarized_results['total_failed_requests_exceptions'] = sum(complete_results)

    complete_results = [r['number_of_200s'] for r in summarized_results['complete_bees']]
    summarized_results['total_number_of_200s'] = sum(complete_results)

    complete_results = [r['number_of_300s'] for r in summarized_results['complete_bees']]
    summarized_results['total_number_of_300s'] = sum(complete_results)

    complete_results = [r['number_of_400s'] for r in summarized_results['complete_bees']]
    summarized_results['total_number_of_400s'] = sum(complete_results)

    complete_results = [r['number_of_500s'] for r in summarized_results['complete_bees']]
    summarized_results['total_number_of_500s'] = sum(complete_results)

    complete_results = [r['requests_per_second'] for r in summarized_results['complete_bees']]
    summarized_results['mean_requests'] = sum(complete_results)

    complete_results = [r['ms_per_request'] for r in summarized_results['complete_bees']]
    if summarized_results['num_complete_bees'] == 0:
        summarized_results['mean_response'] = "no bees are complete"
    else:
        summarized_results['mean_response'] = sum(complete_results) / summarized_results['num_complete_bees']

    summarized_results['tpr_bounds'] = params[0]['tpr']
    summarized_results['rps_bounds'] = params[0]['rps']

    if summarized_results['tpr_bounds'] is not None:
        if summarized_results['mean_response'] < summarized_results['tpr_bounds']:
            summarized_results['performance_accepted'] = True
        else:
            summarized_results['performance_accepted'] = False

    if summarized_results['rps_bounds'] is not None:
        if summarized_results['mean_requests'] > summarized_results['rps_bounds'] and summarized_results['performance_accepted'] is True or None:
            summarized_results['performance_accepted'] = True
        else:
            summarized_results['performance_accepted'] = False

    summarized_results['request_time_cdf'] = _get_request_time_cdf(summarized_results['total_complete_requests'], summarized_results['complete_bees'])
    if csv_filename:
        _create_request_time_cdf_csv(results, summarized_results['complete_bees_params'], summarized_results['request_time_cdf'], csv_filename)

    return summarized_results


def _create_request_time_cdf_csv(results, complete_bees_params, request_time_cdf, csv_filename):
    if csv_filename:
        # csv requires files in text-mode with newlines='' in python3
        # see http://python3porting.com/problems.html#csv-api-changes
        openmode = IS_PY2 and 'w' or 'wt'
        openkwargs = IS_PY2 and {} or {'encoding': 'utf-8', 'newline': ''}
        with open(csv_filename, openmode, openkwargs) as stream:
            writer = csv.writer(stream)
            header = ["% faster than", "all bees [ms]"]
            for p in complete_bees_params:
                header.append("bee %(instance_id)s [ms]" % p)
            writer.writerow(header)
            for i in range(100):
                row = [i, request_time_cdf[i]] if i < len(request_time_cdf) else [i,float("inf")]
                for r in results:
                    if r is not None:
                    	row.append(r['request_time_cdf'][i]["Time in ms"])
                writer.writerow(row)


def _get_request_time_cdf(total_complete_requests, complete_bees):
    # Recalculate the global cdf based on the csv files collected from
    # ab. Can do this by sampling the request_time_cdfs for each of
    # the completed bees in proportion to the number of
    # complete_requests they have
    n_final_sample = 100
    sample_size = 100 * n_final_sample
    n_per_bee = [int(r['complete_requests'] / total_complete_requests * sample_size)
                 for r in complete_bees]
    sample_response_times = []
    for n, r in zip(n_per_bee, complete_bees):
        cdf = r['request_time_cdf']
        for i in range(n):
            j = int(random.random() * len(cdf))
            sample_response_times.append(cdf[j]["Time in ms"])
    sample_response_times.sort()
    # python3 division returns floats so convert back to int
    request_time_cdf = sample_response_times[0:sample_size:int(sample_size / n_final_sample)]

    return request_time_cdf


def _print_results(summarized_results):
    """
    Print summarized load-testing results.
    """
    if summarized_results['exception_bees']:
        print('     %i of your bees didn\'t make it to the action. They might be taking a little longer than normal to'
              ' find their machine guns, or may have been terminated without using "bees down".' % summarized_results['num_exception_bees'])

    if summarized_results['timeout_bees']:
        print('     Target timed out without fully responding to %i bees.' % summarized_results['num_timeout_bees'])

    if summarized_results['num_complete_bees'] == 0:
        print('     No bees completed the mission. Apparently your bees are peace-loving hippies.')
        return

    print('     Complete requests:\t\t%i' % summarized_results['total_complete_requests'])

    print('     Failed requests:\t\t%i' % summarized_results['total_failed_requests'])
    print('          connect:\t\t%i' % summarized_results['total_failed_requests_connect'])
    print('          receive:\t\t%i' % summarized_results['total_failed_requests_receive'])
    print('          length:\t\t%i' % summarized_results['total_failed_requests_length'])
    print('          exceptions:\t\t%i' % summarized_results['total_failed_requests_exceptions'])
    print('     Response Codes:')
    print('          2xx:\t\t%i' % summarized_results['total_number_of_200s'])
    print('          3xx:\t\t%i' % summarized_results['total_number_of_300s'])
    print('          4xx:\t\t%i' % summarized_results['total_number_of_400s'])
    print('          5xx:\t\t%i' % summarized_results['total_number_of_500s'])
    print('     Requests per second:\t%f [#/sec] (mean of bees)' % summarized_results['mean_requests'])
    if 'rps_bounds' in summarized_results and summarized_results['rps_bounds'] is not None:
        print('     Requests per second:\t%f [#/sec] (upper bounds)' % summarized_results['rps_bounds'])

    print('     Time per request:\t\t%f [ms] (mean of bees)' % summarized_results['mean_response'])
    if 'tpr_bounds' in summarized_results and summarized_results['tpr_bounds'] is not None:
        print('     Time per request:\t\t%f [ms] (lower bounds)' % summarized_results['tpr_bounds'])

    print('     50%% responses faster than:\t%f [ms]' % summarized_results['request_time_cdf'][49])
    print('     90%% responses faster than:\t%f [ms]' % summarized_results['request_time_cdf'][89])

    if 'performance_accepted' in summarized_results:
        print('     Performance check:\t\t%s' % summarized_results['performance_accepted'])

    if summarized_results['mean_response'] < 500:
        print('Mission Assessment: Target crushed bee offensive.')
    elif summarized_results['mean_response'] < 1000:
        print('Mission Assessment: Target successfully fended off the swarm.')
    elif summarized_results['mean_response'] < 1500:
        print('Mission Assessment: Target wounded, but operational.')
    elif summarized_results['mean_response'] < 2000:
        print('Mission Assessment: Target severely compromised.')
    else:
        print('Mission Assessment: Swarm annihilated target.')


def attack(url, n, c, **options):
    """
    Test the root url of this site.
    """
    username, key_name, zone, instance_ids = _read_server_list(options.get('zone'))
    headers = options.get('headers', '')
    contenttype = options.get('contenttype', '')
    csv_filename = options.get("csv_filename", '')
    cookies = options.get('cookies', '')
    post_file = options.get('post_file', '')
    keep_alive = options.get('keep_alive', False)
    basic_auth = options.get('basic_auth', '')

    if csv_filename:
        try:
            stream = open(csv_filename, 'w')
        except IOError as e:
            raise IOError("Specified csv_filename='%s' is not writable. Check permissions or specify a different filename and try again." % csv_filename)

    if not instance_ids:
        print('No bees are ready to attack.')
        return

    print('Connecting to the hive.')

    ec2_connection = boto.ec2.connect_to_region(_get_region(zone))

    print('Assembling bees.')

    reservations = ec2_connection.get_all_instances(instance_ids=instance_ids)

    instances = []

    for reservation in reservations:
        instances.extend(reservation.instances)

    instance_count = len(instances)

    if n < instance_count * 2:
        print('bees: error: the total number of requests must be at least %d (2x num. instances)' % (instance_count * 2))
        return
    if c < instance_count:
        print('bees: error: the number of concurrent requests must be at least %d (num. instances)' % instance_count)
        return
    if n < c:
        print('bees: error: the number of concurrent requests (%d) must be at most the same as number of requests (%d)' % (c, n))
        return

    requests_per_instance = int(float(n) / instance_count)
    connections_per_instance = int(float(c) / instance_count)

    print('Each of %i bees will fire %s rounds, %s at a time.' % (instance_count, requests_per_instance, connections_per_instance))

    params = []

    for i, instance in enumerate(instances):
        params.append({
            'i': i,
            'instance_id': instance.id,
            'instance_name': instance.private_dns_name if instance.public_dns_name == "" else instance.public_dns_name,
            'url': url,
            'concurrent_requests': connections_per_instance,
            'num_requests': requests_per_instance,
            'username': username,
            'key_name': key_name,
            'headers': headers,
            'contenttype': contenttype,
            'cookies': cookies,
            'post_file': options.get('post_file'),
            'keep_alive': options.get('keep_alive'),
            'mime_type': options.get('mime_type', ''),
            'tpr': options.get('tpr'),
            'rps': options.get('rps'),
            'basic_auth': options.get('basic_auth')
        })

    print('Stinging URL so it will be cached for the attack.')

    request = Request(url)
    # Need to revisit to support all http verbs.
    if post_file:
        try:
            with open(post_file, 'r') as content_file:
                content = content_file.read()
            if IS_PY2:
                request.add_data(content)
            else:
                # python3 removed add_data method from Request and added data attribute, either bytes or iterable of bytes
                request.data = bytes(content.encode('utf-8'))
        except IOError:
            print('bees: error: The post file you provided doesn\'t exist.')
            return

    if cookies is not '':
        request.add_header('Cookie', cookies)

    if basic_auth is not '':
        authentication = base64.encodestring(basic_auth).replace('\n', '')
        request.add_header('Authorization', 'Basic %s' % authentication)

    # Ping url so it will be cached for testing
    dict_headers = {}
    if headers is not '':
        dict_headers = headers = dict(j.split(':') for j in [i.strip() for i in headers.split(';') if i != ''])

    if contenttype is not '':
        request.add_header("Content-Type", contenttype)

    for key, value in dict_headers.items():
        request.add_header(key, value)

    if url.lower().startswith("https://") and hasattr(ssl, '_create_unverified_context'):
        context = ssl._create_unverified_context()
        response = urlopen(request, context=context)
    else:
        response = urlopen(request)

    response.read()

    print('Organizing the swarm.')
    # Spin up processes for connecting to EC2 instances
    pool = Pool(len(params))
    results = pool.map(_attack, params)

    summarized_results = _summarize_results(results, params, csv_filename)
    print('Offensive complete.')
    _print_results(summarized_results)

    print('The swarm is awaiting new orders.')

    if 'performance_accepted' in summarized_results:
        if summarized_results['performance_accepted'] is False:
            print("Your targets performance tests did not meet our standard.")
            sys.exit(1)
        else:
            print('Your targets performance tests meet our standards, the Queen sends her regards.')
            sys.exit(0)

#############################
### hurl version methods, ###
#############################

def hurl_attack(url, n, c, **options):
    """
    Test the root url of this site.
    """
    print options.get('zone')
    username, key_name, zone, instance_ids = _read_server_list(options.get('zone'))
    headers = options.get('headers', '')
    contenttype = options.get('contenttype', '')
    csv_filename = options.get("csv_filename", '')
    cookies = options.get('cookies', '')
    post_file = options.get('post_file', '')
    keep_alive = options.get('keep_alive', False)
    basic_auth = options.get('basic_auth', '')

    if csv_filename:
        try:
            stream = open(csv_filename, 'w')
        except IOError as e:
            raise IOError("Specified csv_filename='%s' is not writable. Check permissions or specify a different filename and try again." % csv_filename)

    if not instance_ids:
        print('No bees are ready to attack.')
        return

    print('Connecting to the hive.')

    ec2_connection = boto.ec2.connect_to_region(_get_region(zone))

    print('Assembling bees.')

    reservations = ec2_connection.get_all_instances(instance_ids=instance_ids)

    instances = []

    for reservation in reservations:
        instances.extend(reservation.instances)

    instance_count = len(instances)

    if n < instance_count * 2:
        print('bees: error: the total number of requests must be at least %d (2x num. instances)' % (instance_count * 2))
        return
    if c < instance_count:
        print('bees: error: the number of concurrent requests must be at least %d (num. instances)' % instance_count)
        return
    if n < c:
        print('bees: error: the number of concurrent requests (%d) must be at most the same as number of requests (%d)' % (c, n))
        return

    requests_per_instance = int(float(n) / instance_count)
    connections_per_instance = int(float(c) / instance_count)

    print('Each of %i bees will fire %s rounds, %s at a time.' % (instance_count, requests_per_instance, connections_per_instance))

    params = []

    for i, instance in enumerate(instances):
        params.append({
            'i': i,
            'instance_id': instance.id,
            'instance_name': instance.private_dns_name if instance.public_dns_name == "" else instance.public_dns_name,
            'url': url,
            'concurrent_requests': connections_per_instance,
            'num_requests': requests_per_instance,
            'username': username,
            'key_name': key_name,
            'headers': headers,
            'contenttype': contenttype,
            'cookies': cookies,
            'post_file': options.get('post_file'),
            'keep_alive': options.get('keep_alive'),
            'mime_type': options.get('mime_type', ''),
            'tpr': options.get('tpr'),
            'rps': options.get('rps'),
            'basic_auth': options.get('basic_auth'),
            'seconds': options.get('seconds'),
            'rate' : options.get('rate'),
            'long_output' : options.get('long_output'),
            'responses_per' : options.get('responses_per'),
            'verb' : options.get('verb'),
            'threads' : options.get('threads'),
            'fetches' : options.get('fetches'),
            'timeout' : options.get('timeout'),
            'send_buffer' : options.get('send_buffer'),
            'recv_buffer' : options.get('recv_buffer')
        })

    print('Stinging URL so it will be cached for the attack.')

    request = Request(url)
    # Need to revisit to support all http verbs.
    if post_file:
        try:
            with open(post_file, 'r') as content_file:
                content = content_file.read()
            if IS_PY2:
                request.add_data(content)
            else:
                # python3 removed add_data method from Request and added data attribute, either bytes or iterable of bytes
                request.data = bytes(content.encode('utf-8'))
        except IOError:
            print('bees: error: The post file you provided doesn\'t exist.')
            return

    if cookies is not '':
        request.add_header('Cookie', cookies)

    if basic_auth is not '':
        authentication = base64.encodestring(basic_auth).replace('\n', '')
        request.add_header('Authorization', 'Basic %s' % authentication)

    # Ping url so it will be cached for testing
    dict_headers = {}
    if headers is not '':
        dict_headers = headers = dict(j.split(':') for j in [i.strip() for i in headers.split(';') if i != ''])

    if contenttype is not '':
        request.add_header("Content-Type", contenttype)

    for key, value in dict_headers.items():
        request.add_header(key, value)

    if url.lower().startswith("https://") and hasattr(ssl, '_create_unverified_context'):
        context = ssl._create_unverified_context()
        response = urlopen(request, context=context)
    else:
        response = urlopen(request)

    response.read()

    print('Organizing the swarm.')
    # Spin up processes for connecting to EC2 instances
    pool = Pool(len(params))
    results = pool.map(_hurl_attack, params)


    summarized_results = _hurl_summarize_results(results, params, csv_filename)
    print('Offensive complete.')

    _hurl_print_results(summarized_results)

    print('The swarm is awaiting new orders.')

    if 'performance_accepted' in summarized_results:
        if summarized_results['performance_accepted'] is False:
            print("Your targets performance tests did not meet our standard.")
            sys.exit(1)
        else:
            print('Your targets performance tests meet our standards, the Queen sends her regards.')
            sys.exit(0)


def _hurl_attack(params):
    """
    Test the target URL with requests.

    Intended for use with multiprocessing.
    """

    print('Bee %i is joining the swarm.' % params['i'])

    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        pem_path = params.get('key_name') and _get_pem_path(params['key_name']) or None
        if not os.path.isfile(pem_path):
            client.load_system_host_keys()
            client.connect(params['instance_name'], username=params['username'])
        else:
            client.connect(
                params['instance_name'],
                username=params['username'],
                key_filename=pem_path)

        print('Bee %i is firing her machine gun. Bang bang!' % params['i'])

        options = ''
        if params['headers'] is not '':
            for h in params['headers'].split(';'):
                if h != '':
                    options += ' -H "%s"' % h.strip()

        if params['contenttype'] is not '':
            options += ' -H \"Content-Type : %s\"' % params['contenttype']

        stdin, stdout, stderr = client.exec_command('mktemp')
        # paramiko's read() returns bytes which need to be converted back to a str
        params['csv_filename'] = IS_PY2 and stdout.read().strip() or stdout.read().decode('utf-8').strip()
        if params['csv_filename']:
            options += ' -o %(csv_filename)s' % params
        else:
            print('Bee %i lost sight of the target (connection timed out creating csv_filename).' % params['i'])
            return None

        if params['post_file']:
            pem_file_path=_get_pem_path(params['key_name'])
            scpCommand = "scp -q -o 'StrictHostKeyChecking=no' -i %s %s %s@%s:~/" % (pem_file_path, params['post_file'], params['username'], params['instance_name'])
            os.system(scpCommand)
            options += ' -p ~/%s' % params['post_file']

        if params['cookies'] is not '':
            options += ' -H \"Cookie: %s;\"' % params['cookies']

        if params['basic_auth'] is not '':
            options += ' -H \"Authorization : Basic %s\"' % params['basic_auth']

        if params['seconds']:
            options += ' -l %d' % params['seconds']

        if params['rate']:
            options += ' -A %d' % params['rate']

        if params['responses_per']:
            options += ' -L'

        if params['verb'] is not '':
            options += ' -X %s' % params['verb']

        if params['threads']:
            options += ' -t %d' % params['threads']

        if params['fetches']:
            options += ' -f %d' % params['fetches']

        if params['timeout']:
            options += ' -T %d' % params['timeout']

        if params['send_buffer']:
            options += ' -S %d' % params['send_buffer']

        if params['recv_buffer']:
            options += ' -R %d' % params['recv_buffer']

        params['options'] = options

        hurl_command = 'hurl %(url)s -p %(concurrent_requests)s %(options)s -j' % params
        stdin, stdout, stderr = client.exec_command(hurl_command)

        response = defaultdict(int)

        # paramiko's read() returns bytes which need to be converted back to a str
        hurl_results = IS_PY2 and stdout.read() or stdout.read().decode('utf-8')

        #print output for each instance if -o/--long_output is supplied
        def _long_output():
            '''if long_output option,.. display info per bee instead of summarized version'''
            tabspace=''
            singletab=()
            doubletabs=('seconds', 'connect-ms-min',
                       'fetches','bytes-per-sec',
                       'end2end-ms-min',
                       'max-parallel', 'response-codes',
                       'end2end-ms-max', 'connect-ms-max' )
            trippletab=('bytes')
            try:
                print("Bee: {}").format(params['instance_id'])
                for k, v in response.items():
                    if k == 'response-codes':
                        print k
                        tabspace='\t'
                        for rk, rv in v.items():
                            print("{}{}:{}{}").format(tabspace, rk, tabspace+tabspace, rv)
                        continue
                    if k in doubletabs:
                        tabspace='\t\t'
                    elif k in trippletab:
                        tabspace='\t\t\t'
                    else:
                        tabspace='\t'
                    print("{}:{}{}").format(k, tabspace, v)
                print("\n")

            except:
                print("Please check the url entered, also possible no requests were successful Line: 1018")
                return None


        #create the response dict to return to hurl_attack()
        stdin, stdout, stderr = client.exec_command('cat %(csv_filename)s' % params)
        try:
            hurl_json = dict(json.loads(stdout.read().decode('utf-8')))
            for k ,v in hurl_json.items():
                response[k] = v

            #check if user wants output for seperate instances and Sdisplay if so
            long_out_container=[]
            if params['long_output']:
                print(hurl_command)
                print "\n", params['instance_id'] + "\n",params['instance_name'] + "\n" , hurl_results
                _long_output()
                time.sleep(.02)

        except:
            print("Please check the url entered, also possible no requests were successful Line: 1032")
            return None
        finally:
            return response

        print hurl_json['response-codes']
        response['request_time_cdf'] = []
        for row in csv.DictReader(stdout):
            row["Time in ms"] = float(row["Time in ms"])
            response['request_time_cdf'].append(row)
        if not response['request_time_cdf']:
            print('Bee %i lost sight of the target (connection timed out reading csv).' % params['i'])
            return None

        print('Bee %i is out of ammo.' % params['i'])

        client.close()

        return response
    except socket.error as e:
        return e
    except Exception as e:
        traceback.print_exc()
        print()
        raise e

def _hurl_summarize_results(results, params, csv_filename):

    #summarized_results = dict()
    summarized_results = defaultdict(int)
    summarized_results['timeout_bees'] = [r for r in results if r is None]
    summarized_results['exception_bees'] = [r for r in results if type(r) == socket.error]
    summarized_results['complete_bees'] = [r for r in results if r is not None and type(r) != socket.error]
    summarized_results['timeout_bees_params'] = [p for r, p in zip(results, params) if r is None]
    summarized_results['exception_bees_params'] = [p for r, p in zip(results, params) if type(r) == socket.error]
    summarized_results['complete_bees_params'] = [p for r, p in zip(results, params) if r is not None and type(r) != socket.error]
    summarized_results['num_timeout_bees'] = len(summarized_results['timeout_bees'])
    summarized_results['num_exception_bees'] = len(summarized_results['exception_bees'])
    summarized_results['num_complete_bees'] = len(summarized_results['complete_bees'])

    complete_results = [r['fetches'] for r in summarized_results['complete_bees']]
    summarized_results['total_complete_requests'] = sum(complete_results)

    #make summarized_results based of the possible response codes hurl gets
    reported_response_codes = [r['response-codes'] for r in [x for x in summarized_results['complete_bees']]]
    for i in reported_response_codes:
        if isinstance(i, dict):
            for k , v in i.items():
                if k.startswith('20'):
                    summarized_results['total_number_of_200s']+=float(v)
                elif k.startswith('30'):
                    summarized_results['total_number_of_300s']+=float(v)
                elif k.startswith('40'):
                    summarized_results['total_number_of_400s']+=float(v)
                elif k.startswith('50'):
                    summarized_results['total_number_of_500s']+=float(v)

    complete_results = [r['bytes'] for r in summarized_results['complete_bees']]
    summarized_results['total_bytes'] = sum(complete_results)

    complete_results = [r['seconds'] for r in summarized_results['complete_bees']]
    summarized_results['seconds'] = max(complete_results)

    complete_results = [r['connect-ms-max'] for r in summarized_results['complete_bees']]
    summarized_results['connect-ms-max'] = max(complete_results)

    complete_results = [r['1st-resp-ms-max'] for r in summarized_results['complete_bees']]
    summarized_results['1st-resp-ms-max'] = max(complete_results)

    complete_results = [r['1st-resp-ms-mean'] for r in summarized_results['complete_bees']]
    summarized_results['1st-resp-ms-mean'] = sum(complete_results) / summarized_results['num_complete_bees']

    complete_results = [r['fetches-per-sec'] for r in summarized_results['complete_bees']]
    summarized_results['fetches-per-sec'] = sum(complete_results) / summarized_results['num_complete_bees']

    complete_results = [r['fetches'] for r in summarized_results['complete_bees']]
    summarized_results['total-fetches'] = sum(complete_results)

    complete_results = [r['connect-ms-min'] for r in summarized_results['complete_bees']]
    summarized_results['connect-ms-min'] = min(complete_results)

    complete_results = [r['bytes-per-sec'] for r in summarized_results['complete_bees']]
    summarized_results['bytes-per-second-mean'] = sum(complete_results) / summarized_results['num_complete_bees']

    complete_results = [r['end2end-ms-min'] for r in summarized_results['complete_bees']]
    summarized_results['end2end-ms-min'] = sum(complete_results) / summarized_results['num_complete_bees']

    complete_results = [r['mean-bytes-per-conn'] for r in summarized_results['complete_bees']]
    summarized_results['mean-bytes-per-conn'] = sum(complete_results) / summarized_results['num_complete_bees']

    complete_results = [r['connect-ms-mean'] for r in summarized_results['complete_bees']]
    summarized_results['connect-ms-mean'] = sum(complete_results) / summarized_results['num_complete_bees']

    if summarized_results['num_complete_bees'] == 0:
        summarized_results['mean_response'] = "no bees are complete"
    else:
        summarized_results['mean_response'] = sum(complete_results) / summarized_results['num_complete_bees']

    complete_results = [r['connect-ms-mean'] for r in summarized_results['complete_bees']]
    if summarized_results['num_complete_bees'] == 0:
        summarized_results['mean_response'] = "no bees are complete"
    else:
        summarized_results['mean_response'] = sum(complete_results) / summarized_results['num_complete_bees']


    summarized_results['tpr_bounds'] = params[0]['tpr']
    summarized_results['rps_bounds'] = params[0]['rps']

    if summarized_results['tpr_bounds'] is not None:
        if summarized_results['mean_response'] < summarized_results['tpr_bounds']:
            summarized_results['performance_accepted'] = True
        else:
            summarized_results['performance_accepted'] = False

    if summarized_results['rps_bounds'] is not None:
        if summarized_results['mean_requests'] > summarized_results['rps_bounds'] and summarized_results['performance_accepted'] is True or None:
            summarized_results['performance_accepted'] = True
        else:
            summarized_results['performance_accepted'] = False

    summarized_results['request_time_cdf'] = _get_request_time_cdf(summarized_results['total_complete_requests'], summarized_results['complete_bees'])
    if csv_filename:
        _create_request_time_cdf_csv(results, summarized_results['complete_bees_params'], summarized_results['request_time_cdf'], csv_filename)

    return summarized_results


def _hurl_print_results(summarized_results):
    """
    Print summarized load-testing results.
    """
    if summarized_results['exception_bees']:
        print('     %i of your bees didn\'t make it to the action. They might be taking a little longer than normal to'
              ' find their machine guns, or may have been terminated without using "bees down".' % summarized_results['num_exception_bees'])

    if summarized_results['timeout_bees']:
        print('     Target timed out without fully responding to %i bees.' % summarized_results['num_timeout_bees'])

    if summarized_results['num_complete_bees'] == 0:
        print('     No bees completed the mission. Apparently your bees are peace-loving hippies.')
        return
    print('\nSummarized Results')
    print('     Total bytes:\t\t%i' % summarized_results['total_bytes'])
    print('     Seconds:\t\t\t%i' % summarized_results['seconds'])
    print('     Connect-ms-max:\t\t%f' % summarized_results['connect-ms-max'])
    print('     1st-resp-ms-max:\t\t%f' % summarized_results['1st-resp-ms-max'])
    print('     1st-resp-ms-mean:\t\t%f' % summarized_results['1st-resp-ms-mean'])
    print('     Fetches/sec mean:\t\t%f' % summarized_results['fetches-per-sec'])
    print('     connect-ms-min:\t\t%f' % summarized_results['connect-ms-min'])
    print('     Total fetches:\t\t%i' % summarized_results['total-fetches'])
    print('     bytes/sec mean:\t\t%f' % summarized_results['bytes-per-second-mean'])
    print('     end2end-ms-min mean:\t%f' % summarized_results['end2end-ms-min'])
    print('     mean-bytes-per-conn:\t%f' % summarized_results['mean-bytes-per-conn'])
    print('     connect-ms-mean:\t\t%f' % summarized_results['connect-ms-mean'])
    print('\nResponse Codes:')

    print('     2xx:\t\t\t%i' % summarized_results['total_number_of_200s'])
    print('     3xx:\t\t\t%i' % summarized_results['total_number_of_300s'])
    print('     4xx:\t\t\t%i' % summarized_results['total_number_of_400s'])
    print('     5xx:\t\t\t%i' % summarized_results['total_number_of_500s'])
    print

    if 'rps_bounds' in summarized_results and summarized_results['rps_bounds'] is not None:
        print('     Requests per second:\t%f [#/sec] (upper bounds)' % summarized_results['rps_bounds'])


    if 'tpr_bounds' in summarized_results and summarized_results['tpr_bounds'] is not None:
        print('     Time per request:\t\t%f [ms] (lower bounds)' % summarized_results['tpr_bounds'])

    if 'performance_accepted' in summarized_results:
        print('     Performance check:\t\t%s' % summarized_results['performance_accepted'])

    if summarized_results['mean_response'] < 500:
        print('Mission Assessment: Target crushed bee offensive.')
    elif summarized_results['mean_response'] < 1000:
        print('Mission Assessment: Target successfully fended off the swarm.')
    elif summarized_results['mean_response'] < 1500:
        print('Mission Assessment: Target wounded, but operational.')
    elif summarized_results['mean_response'] < 2000:
        print('Mission Assessment: Target severely compromised.')
    else:
        print('Mission Assessment: Swarm annihilated target.')

def _get_new_state_file_name(zone):
    ''' take zone and return multi regional bee file,
    from ~/.bees to ~/.bees.${region}'''
    return STATE_FILENAME+'.'+zone

def _get_existing_regions():
    '''return a list of zone name strings from looking at
    existing region ~/.bees.* files'''
    existing_regions = []
    possible_files = os.listdir(os.path.expanduser('~'))
    for f in possible_files:
        something= re.search(r'\.bees\.(.*)', f)
        existing_regions.append( something.group(1)) if something else "no"
    return existing_regions
