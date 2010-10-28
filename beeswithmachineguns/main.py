import bees
import sys
from optparse import OptionParser

def parse_options():
    """
    Handle the command line arguments for spinning up bees
    """
    command = sys,
    parser = OptionParser(usage="""
bees COMMAND URL [options]

Bees With Machine Guns

A utility for arming (creating) many bees (small EC2 instances) to attack
(load test) targets (web applications).

commands:
  up      start a batch of load testing servers
  attack  begin the attack on a specific url
  down    shutdown and deactivate the load testing servers
    """)

    parser.add_option('-c', '--count', metavar="COUNT", nargs=1,
                       help="number of instance to start")
    parser.add_option('-g', '--group', metavar="GROUP", nargs=1,
                       help="the security group to run the instances under")
    parser.add_option('-z', '--zone',  metavar="ZONE",  nargs=1,
                      help="the availability zone to start the instances in")

    (options, args) = parser.parse_args()

    if not args > 0:
        parser.error("please enter a command")
    command = args[0]
    if command[0] is "attack" and len(args) == 1:
        parser.error("to run an attack you need to present a url")
    url = args[-1].split(",")

    if command == "up":
        bees.up(count=options.count, group=options.group, zone=options.zone)
    elif command == "attack":
        bees.attack(url[0], url[1], url[2])
    elif command == "down":
        bees.down()


def main():
    parse_options()

