import boto3
import json
import time
from boto3.session import Session
import botocore
import requests
import os
import time

def setup_cognito_user_pool():
    boto_session = Session()
    region = boto_session.region_name
    
    # Initialize Cognito client
    cognito_client = boto3.client('cognito-idp', region_name=region)
    
    try:
        # Create User Pool
        user_pool_response = cognito_client.create_user_pool(
            PoolName='MCPServerPool',
            Policies={
                'PasswordPolicy': {
                    'MinimumLength': 8
                }
            }
        )
        pool_id = user_pool_response['UserPool']['Id']
        
        # Create App Client
        app_client_response = cognito_client.create_user_pool_client(
            UserPoolId=pool_id,
            ClientName='MCPServerPoolClient',
            GenerateSecret=False,
            ExplicitAuthFlows=[
                'ALLOW_USER_PASSWORD_AUTH',
                'ALLOW_REFRESH_TOKEN_AUTH'
            ]
        )
        client_id = app_client_response['UserPoolClient']['ClientId']
        
        # Create User
        cognito_client.admin_create_user(
            UserPoolId=pool_id,
            Username='testuser',
            TemporaryPassword='Temp123!',
            MessageAction='SUPPRESS'
        )
        
        # Set Permanent Password
        cognito_client.admin_set_user_password(
            UserPoolId=pool_id,
            Username='testuser',
            Password='MyPassword123!',
            Permanent=True
        )
        
        # Authenticate User and get Access Token
        auth_response = cognito_client.initiate_auth(
            ClientId=client_id,
            AuthFlow='USER_PASSWORD_AUTH',
            AuthParameters={
                'USERNAME': 'testuser',
                'PASSWORD': 'MyPassword123!'
            }
        )
        bearer_token = auth_response['AuthenticationResult']['AccessToken']
        
        # Output the required values
        print(f"Pool id: {pool_id}")
        print(f"Discovery URL: https://cognito-idp.{region}.amazonaws.com/{pool_id}/.well-known/openid-configuration")
        print(f"Client ID: {client_id}")
        print(f"Bearer Token: {bearer_token}")
        
        # Return values if needed for further processing
        return {
            'pool_id': pool_id,
            'client_id': client_id,
            'bearer_token': bearer_token,
            'discovery_url':f"https://cognito-idp.{region}.amazonaws.com/{pool_id}/.well-known/openid-configuration"
        }
        
    except Exception as e:
        print(f"Error: {e}")
        return None

def get_or_create_user_pool(cognito, USER_POOL_NAME):
    response = cognito.list_user_pools(MaxResults=60)
    for pool in response["UserPools"]:
        if pool["Name"] == USER_POOL_NAME:
            user_pool_id = pool["Id"]
            response = cognito.describe_user_pool(
                UserPoolId=user_pool_id
            )
        
            # Get the domain from user pool description
            user_pool = response.get('UserPool', {})
            domain = user_pool.get('Domain')
        
            if domain:
                region = user_pool_id.split('_')[0] if '_' in user_pool_id else REGION
                domain_url = f"https://{domain}.auth.{region}.amazoncognito.com"
                print(f"Found domain for user pool {user_pool_id}: {domain} ({domain_url})")
            else:
                print(f"No domains found for user pool {user_pool_id}")
            return pool["Id"]
    print('Creating new user pool')
    created = cognito.create_user_pool(PoolName=USER_POOL_NAME)
    user_pool_id = created["UserPool"]["Id"]
    user_pool_id_without_underscore_lc = user_pool_id.replace("_", "").lower()
    cognito.create_user_pool_domain(
        Domain=user_pool_id_without_underscore_lc,
        UserPoolId=user_pool_id
    )
    print("Domain created as well")
    return created["UserPool"]["Id"]

def get_or_create_resource_server(cognito, user_pool_id, RESOURCE_SERVER_ID, RESOURCE_SERVER_NAME, SCOPES):
    try:
        existing = cognito.describe_resource_server(
            UserPoolId=user_pool_id,
            Identifier=RESOURCE_SERVER_ID
        )
        return RESOURCE_SERVER_ID
    except cognito.exceptions.ResourceNotFoundException:
        print('creating new resource server')
        cognito.create_resource_server(
            UserPoolId=user_pool_id,
            Identifier=RESOURCE_SERVER_ID,
            Name=RESOURCE_SERVER_NAME,
            Scopes=SCOPES
        )
        return RESOURCE_SERVER_ID

def get_or_create_m2m_client(cognito, user_pool_id, CLIENT_NAME, RESOURCE_SERVER_ID):
    response = cognito.list_user_pool_clients(UserPoolId=user_pool_id, MaxResults=60)
    for client in response["UserPoolClients"]:
        if client["ClientName"] == CLIENT_NAME:
            describe = cognito.describe_user_pool_client(UserPoolId=user_pool_id, ClientId=client["ClientId"])
            return client["ClientId"], describe["UserPoolClient"]["ClientSecret"]
    print('creating new m2m client')
    created = cognito.create_user_pool_client(
        UserPoolId=user_pool_id,
        ClientName=CLIENT_NAME,
        GenerateSecret=True,
        AllowedOAuthFlows=["client_credentials"],
        AllowedOAuthScopes=[f"{RESOURCE_SERVER_ID}/gateway:read", f"{RESOURCE_SERVER_ID}/gateway:write"],
        AllowedOAuthFlowsUserPoolClient=True,
        SupportedIdentityProviders=["COGNITO"],
        ExplicitAuthFlows=["ALLOW_REFRESH_TOKEN_AUTH"]
    )
    return created["UserPoolClient"]["ClientId"], created["UserPoolClient"]["ClientSecret"]

def get_token(user_pool_id: str, client_id: str, client_secret: str, scope_string: str, REGION: str) -> dict:
    try:
        user_pool_id_without_underscore = user_pool_id.replace("_", "")
        url = f"https://{user_pool_id_without_underscore}.auth.{REGION}.amazoncognito.com/oauth2/token"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": scope_string,

        }
        print(client_id)
        response = requests.post(url, headers=headers, data=data)
        response.raise_for_status()
        return response.json()

    except requests.exceptions.RequestException as err:
        return {"error": str(err)}
    
def create_agentcore_role(agent_name):
    iam_client = boto3.client('iam')
    agentcore_role_name = f'agentcore-{agent_name}-role'
    boto_session = Session()
    region = boto_session.region_name
    account_id = boto3.client("sts").get_caller_identity()["Account"]
    role_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "BedrockPermissions",
                "Effect": "Allow",
                "Action": [
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream"
                ],
                "Resource": "*"
            },
            {
                "Effect": "Allow",
                "Action": [
                    "logs:DescribeLogStreams",
                    "logs:CreateLogGroup"
                ],
                "Resource": [
                    f"arn:aws:logs:{region}:{account_id}:log-group:/aws/bedrock-agentcore/runtimes/*"
                ]
            },
            {
                "Effect": "Allow",
                "Action": [
                    "logs:DescribeLogGroups"
                ],
                "Resource": [
                    f"arn:aws:logs:{region}:{account_id}:log-group:*"
                ]
            },
            {
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogStream",
                    "logs:PutLogEvents"
                ],
                "Resource": [
                    f"arn:aws:logs:{region}:{account_id}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*"
                ]
            },
            {
            "Effect": "Allow",
            "Action": [
                "xray:PutTraceSegments",
                "xray:PutTelemetryRecords",
                "xray:GetSamplingRules",
                "xray:GetSamplingTargets"
                ],
             "Resource": [ "*" ]
             },
             {
                "Effect": "Allow",
                "Resource": "*",
                "Action": "cloudwatch:PutMetricData",
                "Condition": {
                    "StringEquals": {
                        "cloudwatch:namespace": "bedrock-agentcore"
                    }
                }
            },
             {
                "Effect": "Allow",
                "Resource": "*",
                "Action": "s3:GetObject",
            },
             {
                "Effect": "Allow",
                "Resource": "*",
                "Action": "lambda:InvokeFunction"
            },
            {
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:*",
                    "iam:PassRole"
                ],
                "Resource": "*"
            },
            {
                "Sid": "GetAgentAccessToken",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:GetWorkloadAccessToken",
                    "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
                    "bedrock-agentcore:GetWorkloadAccessTokenForUserId"
                ],
                "Resource": [
                  f"arn:aws:bedrock-agentcore:{region}:{account_id}:workload-identity-directory/default",
                  f"arn:aws:bedrock-agentcore:{region}:{account_id}:workload-identity-directory/default/workload-identity/{agent_name}-*"
                ]
            }
        ]
    }
    assume_role_policy_document = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AssumeRolePolicy",
                "Effect": "Allow",
                "Principal": {
                    "Service": "bedrock-agentcore.amazonaws.com"
                },
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {
                        "aws:SourceAccount": f"{account_id}"
                    },
                    "ArnLike": {
                        "aws:SourceArn": f"arn:aws:bedrock-agentcore:{region}:{account_id}:*"
                    }
                }
            }
        ]
    }

    assume_role_policy_document_json = json.dumps(
        assume_role_policy_document
    )
    role_policy_document = json.dumps(role_policy)
    # Create IAM Role for the Lambda function
    try:
        agentcore_iam_role = iam_client.create_role(
            RoleName=agentcore_role_name,
            AssumeRolePolicyDocument=assume_role_policy_document_json
        )

        # Pause to make sure role is created
        time.sleep(10)
    except iam_client.exceptions.EntityAlreadyExistsException:
        print("Role already exists -- deleting and creating it again")
        policies = iam_client.list_role_policies(
            RoleName=agentcore_role_name,
            MaxItems=100
        )
        print("policies:", policies)
        for policy_name in policies['PolicyNames']:
            iam_client.delete_role_policy(
                RoleName=agentcore_role_name,
                PolicyName=policy_name
            )
        print(f"deleting {agentcore_role_name}")
        iam_client.delete_role(
            RoleName=agentcore_role_name
        )
        print(f"recreating {agentcore_role_name}")
        agentcore_iam_role = iam_client.create_role(
            RoleName=agentcore_role_name,
            AssumeRolePolicyDocument=assume_role_policy_document_json
        )

    # Attach the AWSLambdaBasicExecutionRole policy
    print(f"attaching role policy {agentcore_role_name}")
    try:
        iam_client.put_role_policy(
            PolicyDocument=role_policy_document,
            PolicyName="AgentCorePolicy",
            RoleName=agentcore_role_name
        )
    except Exception as e:
        print(e)

    return agentcore_iam_role

def create_agentcore_gateway_role(gateway_name):
    iam_client = boto3.client('iam')
    agentcore_gateway_role_name = f'agentcore-{gateway_name}-role'
    boto_session = Session()
    region = boto_session.region_name
    account_id = boto3.client("sts").get_caller_identity()["Account"]
    role_policy = {
        "Version": "2012-10-17",
        "Statement": [{
                "Sid": "VisualEditor0",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:*",
                    "bedrock:*",
                    "agent-credential-provider:*",
                    "iam:PassRole",
                    "secretsmanager:GetSecretValue",
                    "lambda:InvokeFunction"
                ],
                "Resource": "*"
            }
        ]
    }

    assume_role_policy_document = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AssumeRolePolicy",
                "Effect": "Allow",
                "Principal": {
                    "Service": "bedrock-agentcore.amazonaws.com"
                },
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {
                        "aws:SourceAccount": f"{account_id}"
                    },
                    "ArnLike": {
                        "aws:SourceArn": f"arn:aws:bedrock-agentcore:{region}:{account_id}:*"
                    }
                }
            }
        ]
    }

    assume_role_policy_document_json = json.dumps(
        assume_role_policy_document
    )

    role_policy_document = json.dumps(role_policy)
    # Create IAM Role for the Lambda function
    try:
        agentcore_iam_role = iam_client.create_role(
            RoleName=agentcore_gateway_role_name,
            AssumeRolePolicyDocument=assume_role_policy_document_json
        )

        # Pause to make sure role is created
        time.sleep(10)
    except iam_client.exceptions.EntityAlreadyExistsException:
        print("Role already exists -- deleting and creating it again")
        policies = iam_client.list_role_policies(
            RoleName=agentcore_gateway_role_name,
            MaxItems=100
        )
        print("policies:", policies)
        for policy_name in policies['PolicyNames']:
            iam_client.delete_role_policy(
                RoleName=agentcore_gateway_role_name,
                PolicyName=policy_name
            )
        print(f"deleting {agentcore_gateway_role_name}")
        iam_client.delete_role(
            RoleName=agentcore_gateway_role_name
        )
        print(f"recreating {agentcore_gateway_role_name}")
        agentcore_iam_role = iam_client.create_role(
            RoleName=agentcore_gateway_role_name,
            AssumeRolePolicyDocument=assume_role_policy_document_json
        )

    # Attach the AWSLambdaBasicExecutionRole policy
    print(f"attaching role policy {agentcore_gateway_role_name}")
    try:
        iam_client.put_role_policy(
            PolicyDocument=role_policy_document,
            PolicyName="AgentCorePolicy",
            RoleName=agentcore_gateway_role_name
        )
    except Exception as e:
        print(e)

    return agentcore_iam_role


def create_agentcore_gateway_role_s3_smithy(gateway_name):
    iam_client = boto3.client('iam')
    agentcore_gateway_role_name = f'agentcore-{gateway_name}-role'
    boto_session = Session()
    region = boto_session.region_name
    account_id = boto3.client("sts").get_caller_identity()["Account"]
    role_policy = {
        "Version": "2012-10-17",
        "Statement": [{
                "Sid": "VisualEditor0",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:*",
                    "bedrock:*",
                    "agent-credential-provider:*",
                    "iam:PassRole",
                    "secretsmanager:GetSecretValue",
                    "lambda:InvokeFunction",
                    "s3:*",
                ],
                "Resource": "*"
            }
        ]
    }

    assume_role_policy_document = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AssumeRolePolicy",
                "Effect": "Allow",
                "Principal": {
                    "Service": "bedrock-agentcore.amazonaws.com"
                },
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {
                        "aws:SourceAccount": f"{account_id}"
                    },
                    "ArnLike": {
                        "aws:SourceArn": f"arn:aws:bedrock-agentcore:{region}:{account_id}:*"
                    }
                }
            }
        ]
    }

    assume_role_policy_document_json = json.dumps(
        assume_role_policy_document
    )

    role_policy_document = json.dumps(role_policy)
    # Create IAM Role for the Lambda function
    try:
        agentcore_iam_role = iam_client.create_role(
            RoleName=agentcore_gateway_role_name,
            AssumeRolePolicyDocument=assume_role_policy_document_json
        )

        # Pause to make sure role is created
        time.sleep(10)
    except iam_client.exceptions.EntityAlreadyExistsException:
        print("Role already exists -- deleting and creating it again")
        policies = iam_client.list_role_policies(
            RoleName=agentcore_gateway_role_name,
            MaxItems=100
        )
        print("policies:", policies)
        for policy_name in policies['PolicyNames']:
            iam_client.delete_role_policy(
                RoleName=agentcore_gateway_role_name,
                PolicyName=policy_name
            )
        print(f"deleting {agentcore_gateway_role_name}")
        iam_client.delete_role(
            RoleName=agentcore_gateway_role_name
        )
        print(f"recreating {agentcore_gateway_role_name}")
        agentcore_iam_role = iam_client.create_role(
            RoleName=agentcore_gateway_role_name,
            AssumeRolePolicyDocument=assume_role_policy_document_json
        )

    # Attach the AWSLambdaBasicExecutionRole policy
    print(f"attaching role policy {agentcore_gateway_role_name}")
    try:
        iam_client.put_role_policy(
            PolicyDocument=role_policy_document,
            PolicyName="AgentCorePolicy",
            RoleName=agentcore_gateway_role_name
        )
    except Exception as e:
        print(e)

    return agentcore_iam_role

def create_gateway_lambda(lambda_function_code_path) -> dict[str, int]:
    boto_session = Session()
    region = boto_session.region_name

    return_resp = {"lambda_function_arn": "Pending", "exit_code": 1}
    
    # Initialize Cognito client
    lambda_client = boto3.client('lambda', region_name=region)
    iam_client = boto3.client('iam', region_name=region)

    role_name = 'gateway_lambda_iamrole'
    role_arn = ''
    lambda_function_name = 'gateway_lambda'

    print("Reading code from zip file")
    with open(lambda_function_code_path, 'rb') as f:
        lambda_function_code = f.read()

    try:
        print("Creating IAM role for lambda function")

        response = iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps({
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {
                            "Service": "lambda.amazonaws.com"
                        },
                        "Action": "sts:AssumeRole"
                    }
                ]
            }),
            Description="IAM role to be assumed by lambda function"
        )

        role_arn = response['Role']['Arn']

        print("Attaching policy to the IAM role")

        response = iam_client.attach_role_policy(
            RoleName=role_name,
            PolicyArn='arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole'
        )

        print(f"Role '{role_name}' created successfully: {role_arn}")
        time.sleep(100)
    except botocore.exceptions.ClientError as error:
        if error.response['Error']['Code'] == "EntityAlreadyExists":
            response = iam_client.get_role(RoleName=role_name)
            role_arn = response['Role']['Arn']
            print(f"IAM role {role_name} already exists. Using the same ARN {role_arn}")
        else:
            error_message = error.response['Error']['Code'] + "-" + error.response['Error']['Message']
            print(f"Error creating role: {error_message}")
            return_resp['lambda_function_arn'] = error_message

    if role_arn != "":
        print("Creating lambda function")
        # Create lambda function    
        try:
            lambda_response = lambda_client.create_function(
                FunctionName=lambda_function_name,
                Role=role_arn,
                Runtime='python3.12',
                Handler='lambda_function_code.lambda_handler',
                Code = {'ZipFile': lambda_function_code},
                Description='Lambda function example for Bedrock AgentCore Gateway',
                PackageType='Zip'
            )

            return_resp['lambda_function_arn'] = lambda_response['FunctionArn']
            return_resp['exit_code'] = 0
        except botocore.exceptions.ClientError as error:
            if error.response['Error']['Code'] == "ResourceConflictException":
                response = lambda_client.get_function(FunctionName=lambda_function_name)
                lambda_arn = response['Configuration']['FunctionArn']
                print(f"AWS Lambda function {lambda_function_name} already exists. Using the same ARN {lambda_arn}")
                return_resp['lambda_function_arn'] = lambda_arn
            else:
                error_message = error.response['Error']['Code'] + "-" + error.response['Error']['Message']
                print(f"Error creating lambda function: {error_message}")
                return_resp['lambda_function_arn'] = error_message

    return return_resp

def delete_gateway(gateway_client,gatewayId): 
    print("Deleting all targets for gateway", gatewayId)
    list_response = gateway_client.list_gateway_targets(
            gatewayIdentifier = gatewayId,
            maxResults=100
    )
    for item in list_response['items']:
        targetId = item["targetId"]
        print("Deleting target ", targetId)
        gateway_client.delete_gateway_target(
            gatewayIdentifier = gatewayId,
            targetId = targetId
        )
    print("Deleting gateway ", gatewayId)
    gateway_client.delete_gateway(gatewayIdentifier = gatewayId)

def delete_all_gateways(gateway_client):
    try:
        list_response = gateway_client.list_gateways(
            maxResults=100
        )
        for item in list_response['items']:
            gatewayId= item["gatewayId"]
            delete_gateway(gatewayId)
    except Exception as e:
        print(e)
