import bees
import json

sOptions = '{"post_file":"test1.json","contenttype":"application/json"}'
options = json.loads(sOptions)

bees.up(1,'bees-sg','us-east-1b','ami-5d155d37','t2.micro','ubuntu','commerce-bees','subnet-b12880e8')
bees.attack('http://54.89.221.165',2,2,**options)
bees.down()
