import bees
import sys
from optparse import OptionParser, OptionGroup

def parse_options():
    """
    Handle the command line arguments for spinning up bees
    """
    command = sys,
    parser = OptionParser(usage="""
bwmg COMMAND L [options]

Bees with Machine Guns

A utility for arming (creating) many bees (small EC2 instances) to attack
(load test) targets (web applications).

commands:
  up      start a batch of load testing servers
  attack  begin the attack on a specific url
  down    shutdown and deactivate the load testing servers
    """)

    up_group = OptionGroup(parser, "up options", "Options for the up command")

    up_group.add_option('-s', '--servers', metavar="SERVERS", nargs=1,
                        action='store', dest='servers', type='int', default=5,
                        help="number of servers to start")
    up_group.add_option('-g', '--group', metavar="GROUP", nargs=1,
                        action='store', dest='group', type='string', default='staging',
                        help="the security group to run the instances under")
    up_group.add_option('-z', '--zone',  metavar="ZONE",  nargs=1,
                        action='store', dest='zone', type='string', default='us-east-1d',
                        help="the availability zone to start the instances in (e.g. us-east-1d)")
    up_group.add_option('-i', '--instance',  metavar="INSTANCE",  nargs=1,
                        action='store', dest='instance', type='string', default='ami-ff17fb96',
                        help="the instance-id to start each server from (e.g. ami-ff17fb96)")
    up_group.add_option('-k', '--key',  metavar="KEY",  nargs=1,
                        action='store', dest='key', type='string', default='frakkingtoasters',
                        help="the ssh key pair name to use to connect to the new servers")

    parser.add_option_group(up_group)

    attack_group = OptionGroup(parser, "attack options", "Options for the attack command.")

    attack_group.add_option('-n', '--number', metavar="NUMBER", nargs=1,
                        action='store', dest='number', type='int', default=1000,
                        help="number of total connections to make to the target")

    attack_group.add_option('-c', '--concurrent', metavar="CONCURRENT", nargs=1,
                        action='store', dest='concurrent', type='int', default=100,
                        help="number of concurrent connections to make to the target")

    attack_group.add_option('-u', '--url', metavar="URL", nargs=1,
                        action='store', dest='url', type='string',
                        help="url of the target to attack")

    parser.add_option_group(attack_group)

    (options, args) = parser.parse_args()

    if len(args) <= 0:
        parser.error("Please enter a command")

    command = args[0]

    if command == "up":
        bees.up(options.servers, options.group, options.zone, options.instance, options.key)
    elif command == "attack":
        if 'url' not in options:
            parser.error("To run an attack you need to specify a url")
        
        bees.attack(options.url, options.number, options.concurrency)
    elif command == "down":
        bees.down()


def main():
    parse_options()

