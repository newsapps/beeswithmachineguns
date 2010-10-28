#!/bin/env python

"""
The MIT License

Copyright (c) 2010 The Chicago Tribune

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
import time

import boto
import paramiko

EC2_INSTANCE_TYPE = 'm1.small'

STATE_FILENAME = 'theswarm.txt'

# Load state from file

instance_ids = []
if os.path.isfile(STATE_FILENAME):
    with open(STATE_FILENAME, 'r') as f:
        text = f.read()
        instance_ids = text.split('\n')

        print 'Read %i bees from the roster.' % len(instance_ids)

# Utilities

def _write_server_list(instances):
    with open(STATE_FILENAME, 'w') as f:
        f.write('\n'.join([instance.id for instance in instances]))

# Methods

def up(count=5, group='staging', zone='us-east-1d'):
    """
    Startup the load testing server.
    """
    if instance_ids:
        print 'Bees are already assembled and awaiting orders.'
        return

    count = int(count)

    print 'Connecting to the hive.'

    ec2_connection = boto.connect_ec2()

    print 'Attempting to call up %i bees.' % count

    reservation = ec2_connection.run_instances(
        image_id='ami-ff17fb96',
        min_count=count,
        max_count=count,
        key_name='frakkingtoasters',
        security_groups=[group],
        instance_type=EC2_INSTANCE_TYPE,
        placement=zone)

    print 'Waiting for bees to load their machine guns...'

    for instance in reservation.instances:
        while instance.state != 'running':
            print '.'
            time.sleep(5)
            instance.update()

        print 'Bee %s is ready for the attack.' % instance.id

    _write_server_list(reservation.instances)

    print 'The swarm has assembled %i bees.' % len(reservation.instances)

def report():
    """
    Report the status of the load testing servers.
    """
    if not instance_ids:
        print 'No bees have been mobilized.'
        return

    ec2_connection = boto.connect_ec2()

    reservations = ec2_connection.get_all_instances(instance_ids=instance_ids)

    instances = []

    for reservation in reservations:
        instances.extend(reservation.instances)

    for instance in instances:
        print 'Bee %s: %s' % (instance.id, instance.state)

def down():
    """
    Shutdown the load testing server.
    """
    if not instance_ids:
        print 'No bees have been mobilized.'
        return

    print 'Connecting to the hive.'

    ec2_connection = boto.connect_ec2()

    print 'Calling off the swarm.'

    terminated_instance_ids = ec2_connection.terminate_instances(
        instance_ids=instance_ids)

    print 'Stood down %i bees.' % len(terminated_instance_ids)

    os.remove(STATE_FILENAME)

def _attack(params):
    """
    Test the target URL with requests.

    Intended for use with multiprocessing.
    """
    print 'Bee %i is joining the swarm.' % params['i']

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        params['instance_name'],
        username='newsapps',
        key_filename='/Users/sk/.ssh/frakkingtoasters.pem')

    print 'Bee %i is firing his machine gun. Bang bang!' % params['i']

    stdin, stdout, stderr = client.exec_command('ab -r -n %(num_requests)s -c %(concurrent_requests)s -C "sessionid=NotARealSessionID" %(url)s' % params)

    response = {}

    ab_results = stdout.read()
    ms_per_request_search = re.search('Time\ per\ request:\s+([0-9.]+)\ \[ms\]\ \(mean\)', ab_results)

    if not ms_per_request_search:
        print 'Bee %i lost sight of the target (connection timed out).' % params['i']
        return None

    requests_per_second_search = re.search('Requests\ per\ second:\s+([0-9.]+)\ \[#\/sec\]\ \(mean\)', ab_results)
    fifty_percent_search = re.search('\s+50\%\s+([0-9]+)', ab_results)
    ninety_percent_search = re.search('\s+90\%\s+([0-9]+)', ab_results)
    complete_requests_search = re.search('Complete\ requests:\s+([0-9]+)', ab_results)

    response['ms_per_request'] = float(ms_per_request_search.group(1))
    response['requests_per_second'] = float(requests_per_second_search.group(1))
    response['fifty_percent'] = float(fifty_percent_search.group(1))
    response['ninety_percent'] = float(ninety_percent_search.group(1))
    response['complete_requests'] = float(complete_requests_search.group(1))

    print 'Bee %i is out of ammo.' % params['i']

    client.close()

    return response

def _print_results(results):
    """
    Print summarized load-testing results.
    """
    incomplete_results = [r for r in results if r is None]

    if incomplete_results:
        print '     Target failed to fully respond to %i bees.' % len(incomplete_results)

    complete_results = [r['complete_requests'] for r in results if r is not None]
    total_complete_requests = sum(complete_results)
    print '     Complete requests:\t\t%i' % total_complete_requests

    complete_results = [r['requests_per_second'] for r in results if r is not None]
    mean_requests = sum(complete_results)
    print '     Requests per second:\t%f [#/sec] (mean)' % mean_requests

    complete_results = [r['ms_per_request'] for r in results if r is not None]
    mean_response = sum(complete_results) / len(complete_results)
    print '     Time per request:\t\t%f [ms] (mean)' % mean_response

    complete_results = [r['fifty_percent'] for r in results if r is not None]
    mean_fifty = sum(complete_results) / len(complete_results)
    print '     50%% response time:\t\t%f [ms] (mean)' % mean_fifty

    complete_results = [r['ninety_percent'] for r in results if r is not None]
    mean_ninety = sum(complete_results) / len(complete_results)
    print '     90%% response time:\t\t%f [ms] (mean)' % mean_ninety

    if mean_response < 500:
        print 'Mission Assessment: Target crushed bee offensive.'
    elif mean_response < 1000:
        print 'Mission Assessment: Target successfully fended off the swarm.'
    elif mean_response < 1500:
        print 'Mission Assessment: Target wounded, but operational.'
    elif mean_response < 2000:
        print 'Mission Assessment: Target severely compromised.'
    else:
        print 'Mission Assessment: Swarm annihilated target.'

def attack(url, n=10000, c=100):
    """
    Test the root url of this site.
    """
    if not instance_ids:
        print 'No bees are ready to attack.'
        return

    print 'Connecting to the hive.'

    ec2_connection = boto.connect_ec2()

    print 'Assembling bees.'

    reservations = ec2_connection.get_all_instances(instance_ids=instance_ids)

    instances = []

    for reservation in reservations:
        instances.extend(reservation.instances)

    instance_count = len(instances)
    requests_per_instance = int(n) / instance_count
    connections_per_instance = int(c) / instance_count

    print 'Each of %i bees will fire %s rounds, %s at a time.' % (instance_count, requests_per_instance, connections_per_instance)

    params = []

    for i, instance in enumerate(instances):
        params.append({
            'i': i,
            'instance_id': instance.id,
            'instance_name': instance.public_dns_name,
            'url': url,
            'concurrent_requests': connections_per_instance,
            'num_requests': requests_per_instance,
        })

    print 'Stinging URL so it will be cached for the attack.'

    # Ping url so it will be cached for testing
    local('curl %s >> /dev/null' % url)

    print 'Organizing the swarm.'

    # Spin up processes for connecting to EC2 instances
    pool = Pool(len(params))
    results = pool.map(_attack, params)

    print 'Offensive complete.'

    _print_results(results)

    print 'The swarm is awaiting new orders.'