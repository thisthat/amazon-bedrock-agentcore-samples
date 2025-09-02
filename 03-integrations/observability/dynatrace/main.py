from dynatrace import init

init()

from travel_agent import strands_agent_bedrock
import json
import argparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("payload", type=str)
    args = parser.parse_args()
    response = strands_agent_bedrock(json.loads(args.payload))
    print(response)


if __name__ == "__main__":
    main()
