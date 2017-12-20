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
from __future__ import print_function

from future import standard_library
standard_library.install_aliases()
from builtins import zip
from . import bees
try:
    from urllib.parse import urlparse
except ImportError:
    from urllib.parse import urlparse
from optparse import OptionParser, OptionGroup, Values
import threading
import time
import sys

def parse_options():
    """
    Handle the command line arguments for spinning up bees
    """
    parser = OptionParser(usage="""
bees COMMAND [options]

Bees with Machine Guns

A utility for arming (creating) many bees (small EC2 instances) to attack
(load test) targets (web applications).

commands:
  up      Start a batch of load testing servers.
  attack  Begin the attack on a specific url.
  down    Shutdown and deactivate the load testing servers.
  report  Report the status of the load testing servers.
    """)

    up_group = OptionGroup(parser, "up",
                           """In order to spin up new servers you will need to specify at least the -k command, which is the name of the EC2 keypair to use for creating and connecting to the new servers. The bees will expect to find a .pem file with this name in ~/.ssh/. Alternatively, bees can use SSH Agent for the key.""")

    # Required
    up_group.add_option('-k', '--key',  metavar="KEY",  nargs=1,
                        action='store', dest='key', type='string',
                        help="The ssh key pair name to use to connect to the new servers.")

    up_group.add_option('-s', '--servers', metavar="SERVERS", nargs=1,
                        action='store', dest='servers', type='int', default=5,
                        help="The number of servers to start (default: 5).")
    up_group.add_option('-g', '--group', metavar="GROUP", nargs=1,
                        action='store', dest='group', type='string', default='default',
                        help="The security group(s) to run the instances under (default: default).")
    up_group.add_option('-z', '--zone',  metavar="ZONE",  nargs=1,
                        action='store', dest='zone', type='string', default='us-east-1d',
                        help="The availability zone to start the instances in (default: us-east-1d).")
    up_group.add_option('-i', '--instance',  metavar="INSTANCE",  nargs=1,
                        action='store', dest='instance', type='string', default='ami-ff17fb96',
                        help="The instance-id to use for each server from (default: ami-ff17fb96).")
    up_group.add_option('-t', '--type',  metavar="TYPE",  nargs=1,
                        action='store', dest='type', type='string', default='t1.micro',
                        help="The instance-type to use for each server (default: t1.micro).")
    up_group.add_option('-l', '--login',  metavar="LOGIN",  nargs=1,
                        action='store', dest='login', type='string', default='newsapps',
                        help="The ssh username name to use to connect to the new servers (default: newsapps).")
    up_group.add_option('-v', '--subnet',  metavar="SUBNET",  nargs=1,
                        action='store', dest='subnet', type='string', default=None,
                        help="The vpc subnet id in which the instances should be launched. (default: None).")
    up_group.add_option('-b', '--bid', metavar="BID", nargs=1,
                        action='store', dest='bid', type='float', default=None,
                        help="The maximum bid price per spot instance (default: None).")
    up_group.add_option('-x', '--tags', metavar="TAGS", nargs=1,
                        action='store', dest='tags', type='string', default=None,
                        help="custome tags for bee instances")

    parser.add_option_group(up_group)

    attack_group = OptionGroup(parser, "attack",
                               """Beginning an attack requires only that you specify the -u option with the URL you wish to target.""")

    # Required
    attack_group.add_option('-u', '--url', metavar="URL", nargs=1,
                            action='store', dest='url', type='string',
                            help="URL of the target to attack.")
    attack_group.add_option('-K', '--keepalive', metavar="KEEP_ALIVE", nargs=0,
                            action='store', dest='keep_alive', type='string', default=False,
                            help="Keep-Alive connection.")
    attack_group.add_option('-p', '--post-file',  metavar="POST_FILE",  nargs=1,
                            action='store', dest='post_file', type='string', default=False,
                            help="The POST file to deliver with the bee's payload.")
    attack_group.add_option('-m', '--mime-type',  metavar="MIME_TYPE",  nargs=1,
                            action='store', dest='mime_type', type='string', default='text/plain',
                            help="The MIME type to send with the request.")
    attack_group.add_option('-n', '--number', metavar="NUMBER", nargs=1,
                            action='store', dest='number', type='int', default=1000,
                            help="The number of total connections to make to the target (default: 1000).")
    attack_group.add_option('-C', '--cookies', metavar="COOKIES", nargs=1, action='store', dest='cookies',
                            type='string', default='',
                            help='Cookies to send during http requests. The cookies should be passed using standard cookie formatting, separated by semi-colons and assigned with equals signs.')
    attack_group.add_option('-c', '--concurrent', metavar="CONCURRENT", nargs=1,
                            action='store', dest='concurrent', type='int', default=100,
                            help="The number of concurrent connections to make to the target (default: 100).")
    attack_group.add_option('-H', '--headers', metavar="HEADERS", nargs=1,
                            action='store', dest='headers', type='string', default='',
                            help="HTTP headers to send to the target to attack. Multiple headers should be separated by semi-colons, e.g header1:value1;header2:value2")
    attack_group.add_option('-Z', '--ciphers', metavar="CIPHERS", nargs=1,
                            action='store', dest='ciphers', type='string', default='',
                            help="Openssl SSL/TLS cipher name(s) to use for negotiation.  Passed directly to ab's -Z option.  ab-only.")
    attack_group.add_option('-e', '--csv', metavar="FILENAME", nargs=1,
                            action='store', dest='csv_filename', type='string', default='',
                            help="Store the distribution of results in a csv file for all completed bees (default: '').")
    attack_group.add_option('-P', '--contenttype', metavar="CONTENTTYPE", nargs=1,
                            action='store', dest='contenttype', type='string', default='text/plain',
                            help="ContentType header to send to the target of the attack.")
    attack_group.add_option('-I', '--sting', metavar="sting", nargs=1,
                            action='store', dest='sting', type='int', default=1,
                            help="The flag to sting (ping to cache) url before attack (default: 1). 0: no sting, 1: sting sequentially, 2: sting in parallel")
    attack_group.add_option('-S', '--seconds', metavar="SECONDS", nargs=1,
                            action='store', dest='seconds', type='int', default=60,
                            help= "hurl only: The number of total seconds to attack the target (default: 60).")
    attack_group.add_option('-X', '--verb', metavar="VERB", nargs=1,
                            action='store', dest='verb', type='string', default='',
                            help= "hurl only: Request command -HTTP verb to use -GET/PUT/etc. Default GET")
    attack_group.add_option('-M', '--rate', metavar="RATE", nargs=1,
                            action='store', dest='rate', type='int',
                            help= "hurl only: Max Request Rate.")
    attack_group.add_option('-a', '--threads', metavar="THREADS", nargs=1,
                            action='store', dest='threads', type='int', default=1,
                            help= "hurl only: Number of parallel threads. Default: 1")
    attack_group.add_option('-f', '--fetches', metavar="FETCHES", nargs=1,
                            action='store', dest='fetches', type='int', 
                            help= "hurl only: Num fetches per instance.")
    attack_group.add_option('-d', '--timeout', metavar="TIMEOUT", nargs=1,
                            action='store', dest='timeout', type='int',
                            help= "hurl only: Timeout (seconds).")
    attack_group.add_option('-E', '--send_buffer', metavar="SEND_BUFFER", nargs=1,
                            action='store', dest='send_buffer', type='int',
                            help= "hurl only: Socket send buffer size.")
    attack_group.add_option('-F', '--recv_buffer', metavar="RECV_BUFFER", nargs=1,
                            action='store', dest='recv_buffer', type='int',
                            help= "hurl only: Socket receive buffer size.")
    # Optional
    attack_group.add_option('-T', '--tpr', metavar='TPR', nargs=1, action='store', dest='tpr', default=None, type='float',
                            help='The upper bounds for time per request. If this option is passed and the target is below the value a 1 will be returned with the report details (default: None).')
    attack_group.add_option('-R', '--rps', metavar='RPS', nargs=1, action='store', dest='rps', default=None, type='float',
                            help='The lower bounds for request per second. If this option is passed and the target is above the value a 1 will be returned with the report details (default: None).')
    attack_group.add_option('-A', '--basic_auth', metavar='basic_auth', nargs=1, action='store', dest='basic_auth', default='', type='string',
                            help='BASIC authentication credentials, format auth-username:password (default: None).')
    attack_group.add_option('-j', '--hurl', metavar="HURL_COMMANDS",
                            action='store_true', dest='hurl',
                            help="use hurl")
    attack_group.add_option('-o', '--long_output', metavar="LONG_OUTPUT",
                            action='store_true', dest='long_output',
                            help="display hurl output")
    attack_group.add_option('-L', '--responses_per', metavar="RESPONSE_PER",
                            action='store_true', dest='responses_per',
                            help="hurl only: Display http(s) response codes per interval instead of request statistics")


    parser.add_option_group(attack_group)

    (options, args) = parser.parse_args()

    if len(args) <= 0:
        parser.error('Please enter a command.')

    command = args[0]
    #set time for in between threads
    delay = 0.2

    if command == 'up':
        if not options.key:
            parser.error('To spin up new instances you need to specify a key-pair name with -k')

        if options.group == 'default':
            print('New bees will use the "default" EC2 security group. Please note that port 22 (SSH) is not normally open on this group. You will need to use to the EC2 tools to open it before you will be able to attack.')
        zone_len = options.zone.split(',')
        if len(zone_len) > 1:
            if len(options.instance.split(',')) != len(zone_len):
                print("Your instance count does not match zone count")
                sys.exit(1)
            else:
                ami_list = [a for a in options.instance.split(',')]
                zone_list = [z for z in zone_len]
                # for each ami and zone set zone and instance
                for tup_val in zip(ami_list, zone_list):
                    options.instance, options.zone = tup_val
                    threading.Thread(target=bees.up, args=(options.servers, options.group,
                                                            options.zone, options.instance,
                                                            options.type,options.login,
                                                            options.key, options.subnet,
                                                            options.tags, options.bid)).start()
                    #time allowed between threads
                    time.sleep(delay)
        else:
            bees.up(options.servers, options.group, options.zone, options.instance, options.type, options.login, options.key, options.subnet, options.tags, options.bid)

    elif command == 'attack':
        if not options.url:
            parser.error('To run an attack you need to specify a url with -u')

        regions_list = []
        for region in bees._get_existing_regions():
                regions_list.append(region)

        # urlparse needs a scheme in the url. ab doesn't, so add one just for the sake of parsing.
        # urlparse('google.com').path == 'google.com' and urlparse('google.com').netloc == '' -> True
        parsed = urlparse(options.url) if '://' in options.url else urlparse('http://'+options.url)
        if parsed.path == '':
            options.url += '/'
        additional_options = dict(
            cookies=options.cookies,
            ciphers=options.ciphers,
            headers=options.headers,
            post_file=options.post_file,
            keep_alive=options.keep_alive,
            mime_type=options.mime_type,
            csv_filename=options.csv_filename,
            tpr=options.tpr,
            rps=options.rps,
            basic_auth=options.basic_auth,
            contenttype=options.contenttype,
            sting=options.sting,
            hurl=options.hurl,
            seconds=options.seconds,
            rate=options.rate,
            long_output=options.long_output,
            responses_per=options.responses_per,
            verb=options.verb,
            threads=options.threads,
            fetches=options.fetches,
            timeout=options.timeout,
            send_buffer=options.send_buffer,
            recv_buffer=options.recv_buffer
        )
        if options.hurl:
            for region in regions_list:
                additional_options['zone'] = region
                threading.Thread(target=bees.hurl_attack, args=(options.url, options.number, options.concurrent),
                    kwargs=additional_options).start()
                #time allowed between threads
                time.sleep(delay)
        else:
            for region in regions_list:
                additional_options['zone'] = region
                threading.Thread(target=bees.attack, args=(options.url, options.number,
                    options.concurrent), kwargs=additional_options).start()
                #time allowed between threads
                time.sleep(delay)

    elif command == 'down':
        bees.down()
    elif command == 'report':
        bees.report()

def main():
    parse_options()
