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
import sys
import time
import urllib2
import csv
import math

import boto
import paramiko

EC2_INSTANCE_TYPE = 't1.micro'
STATE_FILENAME = os.path.expanduser('~/.bees')

# Utilities

def _read_server_list():
    instance_ids = []

    if not os.path.isfile(STATE_FILENAME):
        return (None, None, None)

    with open(STATE_FILENAME, 'r') as f:
        username = f.readline().strip()
        key_name = f.readline().strip()
        text = f.read()
        instance_ids = text.split('\n')

        print 'Read %i bees from the roster.' % len(instance_ids)

    return (username, key_name, instance_ids)

def _write_server_list(username, key_name, instances):
    with open(STATE_FILENAME, 'w') as f:
        f.write('%s\n' % username)
        f.write('%s\n' % key_name)
        f.write('\n'.join([instance.id for instance in instances]))

def _delete_server_list():
    os.remove(STATE_FILENAME)

def _get_pem_path(key):
    return os.path.expanduser('~/.ssh/%s.pem' % key)

# Methods

def up(count, group, zone, image_id, username, key_name):
    """
    Startup the load testing server.
    """
    existing_username, existing_key_name, instance_ids = _read_server_list()

    if instance_ids:
        print 'Bees are already assembled and awaiting orders.'
        return

    count = int(count)

    pem_path = _get_pem_path(key_name)

    if not os.path.isfile(pem_path):
        print 'No key file found at %s' % pem_path
        return

    print 'Connecting to the hive.'

    ec2_connection = boto.connect_ec2()

    print 'Attempting to call up %i bees.' % count

    reservation = ec2_connection.run_instances(
        image_id=image_id,
        min_count=count,
        max_count=count,
        key_name=key_name,
        security_groups=[group],
        instance_type=EC2_INSTANCE_TYPE,
        placement=zone)

    print 'Waiting for bees to load their machine guns...'

    instance_ids = []

    for instance in reservation.instances:
        while instance.state != 'running':
            print '.'
            time.sleep(5)
            instance.update()

        instance_ids.append(instance.id)

        print 'Bee %s is ready for the attack.' % instance.id

    ec2_connection.create_tags(instance_ids, { "Name": "a bee!" })

    _write_server_list(username, key_name, reservation.instances)

    print 'The swarm has assembled %i bees.' % len(reservation.instances)

def report():
    """
    Report the status of the load testing servers.
    """
    username, key_name, instance_ids = _read_server_list()

    if not instance_ids:
        print 'No bees have been mobilized.'
        return

    ec2_connection = boto.connect_ec2()

    reservations = ec2_connection.get_all_instances(instance_ids=instance_ids)

    instances = []

    for reservation in reservations:
        instances.extend(reservation.instances)

    for instance in instances:
        print 'Bee %s: %s @ %s' % (instance.id, instance.state, instance.ip_address)

def down():
    """
    Shutdown the load testing server.
    """
    username, key_name, instance_ids = _read_server_list()

    if not instance_ids:
        print 'No bees have been mobilized.'
        return

    print 'Connecting to the hive.'

    ec2_connection = boto.connect_ec2()

    print 'Calling off the swarm.'

    terminated_instance_ids = ec2_connection.terminate_instances(
        instance_ids=instance_ids)

    print 'Stood down %i bees.' % len(terminated_instance_ids)

    _delete_server_list()

def _attack(params):
    """
    Test the target URL with requests.

    Intended for use with multiprocessing.
    """
    print 'Bee %i is joining the swarm.' % params['i']

    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            params['instance_name'],
            username=params['username'],
            key_filename=_get_pem_path(params['key_name']))

        print 'Bee %i is firing his machine gun. Bang bang!' % params['i']

        stdin, stdout, stderr = client.exec_command('tempfile -s .csv')
        params['csv_filename'] = stdout.read().strip()
        if not params['csv_filename']:
            print 'Bee %i lost sight of the target (connection timed out creating csv_filename).' % params['i']
            return None

        stdin, stdout, stderr = client.exec_command('ab -r -n %(num_requests)s -c %(concurrent_requests)s -e %(csv_filename)s -C "sessionid=NotARealSessionID" %(url)s' % params)

        response = {}

        ab_results = stdout.read()
        ms_per_request_search = re.search('Time\ per\ request:\s+([0-9.]+)\ \[ms\]\ \(mean\)', ab_results)

        if not ms_per_request_search:
            print 'Bee %i lost sight of the target (connection timed out running ab).' % params['i']
            return None

        requests_per_second_search = re.search('Requests\ per\ second:\s+([0-9.]+)\ \[#\/sec\]\ \(mean\)', ab_results)
        complete_requests_search = re.search('Complete\ requests:\s+([0-9]+)', ab_results)

        response['ms_per_request'] = float(ms_per_request_search.group(1))
        response['requests_per_second'] = float(requests_per_second_search.group(1))
        response['complete_requests'] = float(complete_requests_search.group(1))

        stdin, stdout, stderr = client.exec_command('cat %(csv_filename)s' % params)
        response['request_time_cdf'] = []
        for row in csv.DictReader(stdout):
            row["Time in ms"] = float(row["Time in ms"])
            response['request_time_cdf'].append(row)
        if not response['request_time_cdf']:
            print 'Bee %i lost sight of the target (connection timed out reading csv).' % params['i']
            return None

        print 'Bee %i is out of ammo.' % params['i']

        client.close()

        return response
    except socket.error, e:
        return e


def _print_results(results, csv_filename):
    """
    Print summarized load-testing results.
    """
    timeout_bees = [r for r in results if r is None]
    exception_bees = [r for r in results if type(r) == socket.error]
    complete_bees = [r for r in results if r is not None and type(r) != socket.error]

    num_timeout_bees = len(timeout_bees)
    num_exception_bees = len(exception_bees)
    num_complete_bees = len(complete_bees)

    if exception_bees:
        print '     %i of your bees didn\'t make it to the action. They might be taking a little longer than normal to find their machine guns, or may have been terminated without using "bees down".' % num_exception_bees

    if timeout_bees:
        print '     Target timed out without fully responding to %i bees.' % num_timeout_bees

    if num_complete_bees == 0:
        print '     No bees completed the mission. Apparently your bees are peace-loving hippies.'
        return

    complete_results = [r['complete_requests'] for r in complete_bees]
    total_complete_requests = sum(complete_results)
    print '     Complete requests:\t\t%i' % total_complete_requests

    complete_results = [r['requests_per_second'] for r in complete_bees]
    mean_requests = sum(complete_results)
    print '     Requests per second:\t%f [#/sec]' % mean_requests

    complete_results = [r['ms_per_request'] for r in complete_bees]
    mean_response = sum(complete_results) / num_complete_bees
    print '     Time per request:\t\t%f [ms] (mean of bees)' % mean_response

    # Recalculate the global cdf based on the csv files collected from
    # ab. First need to calculate the probability density function to
    # back out the cdf and get the 50% and 90% values. Since values
    # can vary over several orders of magnitude, use logarithmic
    # binning here.
    tmin = min(r['request_time_cdf'][0]['Time in ms'] for r in complete_bees)
    tmax = max(r['request_time_cdf'][-1]['Time in ms'] for r in complete_bees)
    ltmin, ltmax = map(math.log, [tmin, tmax])
    class Bin(object):
        def __init__(self, lwrbnd, uprbnd, mass=0.0):
            self.lwrbnd = lwrbnd
            self.uprbnd = uprbnd
            self.mass = mass
        def width(self):
            return self.uprbnd - self.lwrbnd
    request_time_pdf = []
    nbins = 1000
    factor = math.exp((ltmax-ltmin)/nbins)
    lwrbnd = tmin
    for b in range(nbins):
        # lwrbnd = tmin*factor**b
        # uprbnd = tmax*factor**(b+1)
        uprbnd = lwrbnd * factor
        request_time_pdf.append(Bin(lwrbnd, uprbnd))
        lwrbnd = uprbnd
    for r in complete_bees:
        pct_complete = float(r["complete_requests"]) / total_complete_requests
        for i, j in zip(r['request_time_cdf'][:-1], r['request_time_cdf'][1:]):
            bmin = int(math.log(i["Time in ms"]/tmin)/math.log(factor))
            bmax = int(math.log(j["Time in ms"]/tmin)/math.log(factor))
            bmax = min(nbins-1, bmax)
            s = 0.0
            for b in range(bmin, bmax+1):
                bin = request_time_pdf[b]
                _tmin = max(bin.lwrbnd, i["Time in ms"]) # overlapping boundary
                _tmax = min(bin.uprbnd, j["Time in ms"]) # overlapping boundary
                _w = j["Time in ms"] - i["Time in ms"]
                if _w > 0.0:
                    proportion = (_tmax - _tmin) / _w
                    bin.mass += proportion * pct_complete * 0.01
    total_mass = sum(b.mass for b in request_time_pdf)
    cumulative_mass = 0.0
    request_time_cdf = [tmin]
    for bin in request_time_pdf:
        cumulative_mass += bin.mass
        while cumulative_mass / total_mass * 100 > len(request_time_cdf):
            request_time_cdf.append(bin.uprbnd)
    print request_time_cdf, len(request_time_cdf), cumulative_mass, len(request_time_pdf)

    print '     50%% responses faster than:\t%f [ms]' % request_time_cdf[49]
    print '     90%% responses faster than:\t%f [ms]' % request_time_cdf[89]

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
    
def attack(url, n, c, csv_filename):
    """
    Test the root url of this site.
    """
    username, key_name, instance_ids = _read_server_list()

    if csv_filename:
        try:
            stream = open(csv_filename, 'w')
        except IOError, e:
            raise IOError("Specified csv_filename='%s' is not writable. Check permissions or specify a different filename and try again." % csv_filename)
    
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
    requests_per_instance = int(float(n) / instance_count)
    connections_per_instance = int(float(c) / instance_count)

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
            'username': username,
            'key_name': key_name,
        })

    print 'Stinging URL so it will be cached for the attack.'

    # Ping url so it will be cached for testing
    urllib2.urlopen(url)

    print 'Organizing the swarm.'

    # Spin up processes for connecting to EC2 instances
    pool = Pool(len(params))
    results = pool.map(_attack, params)

    print 'Offensive complete.'

    _print_results(results, csv_filename)

    print 'The swarm is awaiting new orders.'
