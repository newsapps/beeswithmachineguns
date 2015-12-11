import boto
import boto.ec2

from boto.ec2.connection import EC2Connection

boto.set_stream_logger('boto')
ec2 = boto.ec2.connect_to_region('us-west-2')
ec2_connection = EC2Connection()

reservation = ec2_connection.run_instances(
        image_id='ami-5d155d37',
        min_count=1,
        max_count=1,
        key_name='commerce-bees',
        security_groups=None,
        instance_type='m3.medium',
        placement='us-west-2b',
        subnet_id='subnet-b12880e8')
"""
#!/usr/bin/env python

import boto
import boto.ec2
from boto.ec2.connection import EC2Connection
from boto.ec2.blockdevicemapping import BlockDeviceType
from boto.ec2.blockdevicemapping import BlockDeviceMapping

access_key = 'AKIAJDMWMOLVP4WEG74A'
secret_key = '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'

#conn = boto.ec2.connect_to_region('us-east-1', access_key, secret_key)
#reservation = conn.run_instances('ami-5d155d37', instance_type='m1.small')


def launchBaseInstance(ami='your-default-ami'):
	'''Launch a single instance of the provided ami'''
        ec2_connection = EC2Connection(access_key, secret_key)
        
        reservation = ec2_connection.run_instances(
        image_id='ami-5d155d37',
        min_count=1,
        max_count=1,
        key_name='commerce-bees',
        security_groups=None,
        instance_type='m3.medium',
        placement='us-west-2b',
        subnet_id='subnet-b12880e8')
                                 

        
launchBaseInstance()

#import boto
#s3 = boto.connect_s3()

#bucket = s3.create_bucket('media.yourdomain.com')  # bucket names must be unique

	reservation = ec2_connection.run_instances(
        image_id='ami-f0091d91',
        min_count=1,
        max_count=1,
        key_name='commerce-bees',
        security_groups=['offers'],
        instance_type='m3.medium',
        placement='us-west-2b',
        subnet_id=None)
        
def _get_region(zone):
    return zone if 'gov' in zone else zone[:-1] # chop off the "d" in the "us-east-1d" to get the "Region"

ec2_connection = E2Connection()
ec2_connection = boto.ec2.connect_to_region('us-west-1a')

if ec2_connection == None:
        raise Exception("Invalid zone specified? Unable to connect to region using zone name")
     
reservation = ec2_connection.run_instances(
        image_id=image_id,
        min_count=count,
        max_count=count,
        key_name=key_name,
        security_groups=[group] if subnet is None else _get_security_group_ids(ec2_connection, [group], subnet),
        instance_type=instance_type,
        placement=None if 'gov' in zone else zone,
        subnet_id=subnet)

		
try:
	#def up(count, group, zone, image_id, instance_type, username, key_name, subnet, bid = None):
	bees.up(4,'bees-sg','us-east-1b','ami-5d155d37','m3.medium','ubuntu','commerce-bees','subnet-b12880e8')
except EvironmentError as e:
	print("Error: %" % format(e))
	sys.exit(1)
        """