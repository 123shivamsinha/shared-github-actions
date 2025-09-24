from datetime import datetime
import time
import ast
import requests
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import random
import json
import sys
import os
import subprocess
from kpghalogger import KpghaLogger
logger = KpghaLogger()

def set_target_registry():
    """Set target registry based on platform and registry type"""
    try:
        platform = os.getenv('PLATFORM')
        registry = os.getenv('REGISTRY')

        if not platform or not registry:
            logger.error("PLATFORM or REGISTRY environment variables are not set.")
            raise ValueError("PLATFORM and REGISTRY must be set.")

        registry_map = {
            'docker-ocpbaseimages': {
                'prod': os.getenv('OCP_PROD_IMAGE_REGISTRY'),
                'non-prod': os.getenv('OCP_NPROD_IMAGE_REGISTRY')
            },
             'docker-baseimages': {
                'prod': os.getenv('AKS_PROD_IMAGE_REGISTRY'),
                'non-prod': os.getenv('AKS_NPROD_IMAGE_REGISTRY')
            },
               'openshift-ecosystem': {
                'prod': os.getenv('OPENSHIFT_PROD_IMAGE_REGISTRY'),
                'non-prod': os.getenv('OPENSHIFT_NPROD_IMAGE_REGISTRY')
            },
              'docker-opensourceimages': {
                'prod': os.getenv('OPENSOURCE_PROD_IMAGE_REGISTRY'),
                'non-prod': os.getenv('OPENSOURCE_NPROD_IMAGE_REGISTRY')
            }
        }

        target_registry = registry_map.get(platform, {}).get(registry)
        if not target_registry:
            raise KeyError(f"Invalid platform '{platform}' or registry '{registry}'")

        # Directly write outputs
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write(f'target-registry={target_registry}\n')
            f.write(f'result=success\n')

        logger.info(f"KP registry: {target_registry}")
        os.system(f"echo 'target-registry={target_registry}' >> $GITHUB_OUTPUT")
        return target_registry

    except Exception as e:
        logger.error(f"Error in while setting  target registry: {str(e)}")
        raise

def scan_image():
    image_names = os.getenv('IMAGE_NAME', '').split(',')
    scan_results_files = []

    for image_name in image_names:
        image_name = image_name.strip()
        if not image_name:
            continue

        try:
            # Ensure scan_results directory exists
            os.makedirs("scan_results", exist_ok=True)

            # Pull the image before scanning
            logger.info(f"Pulling image: {image_name}")
            pull_result = subprocess.run(["docker", "pull", image_name], capture_output=True, text=True)

            if pull_result.returncode != 0:
                logger.error(f"Failed to pull image: {image_name}")
                logger.error(f'Error response while pulling docker image{pull_result.stderr}')
                continue

            # Generate a safe filename
            safe_image_name = image_name.replace(":", "_").replace("/", "_")
            json_file = f"scan_results/{safe_image_name}.json"

            # Run twistcli scan
            command = (
                f"./twistcli images scan "
                f"--address {os.getenv('PRISM_URL')} "
                f"--user {os.getenv('PROD_PCC_USER')} "
                f"--password {os.getenv('PROD_PCC_PASS')} "
                f"--output-file {json_file} "
                f"{image_name}"
            )
            logger.info(f"Scanning image: {image_name}")
            result = os.system(command)

            if result != 0:
                logger.error(f"Failed to scan image: {image_name}")
                continue

            # Export the JSON file path as GitHub Actions output
            os.system(f"echo 'scan-results={json_file}' >> $GITHUB_OUTPUT")
            logger.info(f"Scan completed. Results saved to {json_file}")
            scan_results_files.append(json_file)

        except Exception as e:
            logger.error(f"Unexpected error scanning image {image_name}: {e}")
            continue

    if not scan_results_files:
        logger.error("No scan results generated. Exiting.")
        sys.exit(1)
    
#docker build function
def build_docker_image():
    """Build Docker image with platform-specific labels and tags"""
    image_url = os.getenv('IMAGE_URL')
    image_tag = os.getenv('IMAGE_TAG')

    if not image_url or not image_tag:
        logger.error("Missing IMAGE_URL or IMAGE_TAG environment variables.")
        sys.exit(1)

    build_args = {
        'PUBLISHED_BY': os.getenv('GITHUB_ACTOR'),
        'BUILD_URL': os.getenv('BUILD_URL', 'N/A'),
        'BUILD_DATE': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'GIT_BRANCH': os.getenv('GITHUB_BRANCH', 'N/A'),
        'GIT_COMMIT': os.getenv('GITHUB_COMMIT', 'N/A'),
        'GIT_COMMIT_SHA': os.getenv('GIT_COMMIT_SHA', 'N/A'),
        'GIT_URL': os.getenv('GIT_URL', 'N/A'),
        'KP_ATLAS_ID': os.getenv('ATLAS_APP_ID', 'N/A'),
        'KP_HOST_IDENTIFIER': os.getenv('DEPLOYMENT_HOST', 'N/A'),
        'KP_TECHNICAL_OWNER_EMAIL_ID': os.getenv('MAIL_ID', 'N/A'),
        'KP_TECHNICAL_OWNER': os.getenv('GITHUB_ACTOR', 'N/A'),
        'BUILD_SYSTEM': 'GHA',
        'BUILD_NUMBER': os.getenv('GITHUB_RUN_NUMBER', 'N/A'),
        'BUILD_ID': os.getenv('GITHUB_RUN_ID', 'N/A'),
        'REPOSITORY': os.getenv('GITHUB_REPOSITORY', 'N/A'),
        'WORKFLOW': os.getenv('GITHUB_WORKFLOW', 'N/A')
    }

    try:
        with open("Dockerfile", "w") as dockerfile:
            dockerfile.write(f"FROM {image_url}:{image_tag}\n")

        label_args = " ".join([f'--label "{k}={v}"' for k, v in build_args.items()])
        build_cmd = f"docker build -t {image_url}:{image_tag} {label_args} ."
        subprocess.run(build_cmd, shell=True, check=True)
        logger.info(f"Successfully built image: {image_url}:{image_tag}")
        os.system(f"echo 'docker-image={image_url}:{image_tag}' >> $GITHUB_OUTPUT") 
        return f"{image_url}:{image_tag}"

    except subprocess.CalledProcessError as e:
        logger.error(f"Error building image: {str(e)}")
        sys.exit(1)


def push_docker_image():
    """Push Docker image to target registry"""
    approver_id = os.getenv('GITHUB_ACTOR')
    image_name = os.getenv('IMAGE_NAME')
    image_url = os.getenv('IMAGE_URL') 
    registry_folder = os.getenv('REGISTRY_FOLDER', '')
    custom_tag = os.getenv('CUSTOM_TAG') 
    target_registry = os.getenv('TARGET_REGISTRY')
    image_tag = os.getenv('IMAGE_TAG') 
    platform = os.getenv('PLATFORM')
    image_path = os.getenv('IMAGE_PATH')

    if not all([image_name, target_registry]):
        logger.error("Missing required environment variables: IMAGE_NAME or TARGET_REGISTRY")
        sys.exit(1)

    try:
        # Construct target image path with proper handling of websphere-liberty cases
        if '/websphere' in image_name:
            base_image_name = 'websphere-liberty'
        else:
            base_image_name = image_url

        # Build the target image path
        if custom_tag:
            image_path = f"/{registry_folder}/{base_image_name}/{custom_tag}"
            target_image = f"{target_registry}/{registry_folder}/{base_image_name}:{custom_tag}"
        else:
            image_path = f"/{registry_folder}/{base_image_name}/{image_tag}"
            target_image = f"{target_registry}/{registry_folder}/{base_image_name}:{image_tag}"

        # Normalize any double slashes (// -> /)
        target_image = target_image.replace('//', '/')
        image_path = image_path.replace('//', '/')

        with open("Dockerfile", "w") as dockerfile:
            dockerfile.write(f"FROM {image_name}\n")

        build_cmd = f"docker build -t {image_name} ."
        subprocess.run(build_cmd, shell=True, check=True)

        tag_cmd = f"docker tag {image_name} {target_image}"
        subprocess.run(tag_cmd, shell=True, check=True)

        push_cmd = f"docker push {target_image}"
        subprocess.run(push_cmd, shell=True, check=True)

        cleanup_cmd = f"docker rmi --force {image_name} {target_image}"
        subprocess.run(cleanup_cmd, shell=True, check=True)

        logger.info(f"Successfully pushed image: https://{target_registry}/ui/repos/tree/General/{platform}{image_path}")
        os.system(f"echo 'image-url=https://{target_registry}/ui/repos/tree/General/{platform}{image_path}' >> $GITHUB_OUTPUT")
        return target_image

    except Exception as e:
        logger.error(f"Failed to push image: {e}")
        sys.exit(1)

def push_multiple_docker_images():
    """Tag, push, and clean up multiple Docker images from image list"""
    image_names = os.getenv('IMAGE_NAME')
    vendor_image_registry = os.getenv('TARGET_REGISTRY')
    project_name = os.getenv('REGISTRY_FOLDER')
    target_image = f"{vendor_image_registry}/{project_name}"
    build_args = {
        'PUBLISHED_BY': os.getenv('GITHUB_ACTOR'),
        'BUILD_URL': os.getenv('BUILD_URL', 'N/A'),
        'BUILD_DATE': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'GIT_BRANCH': os.getenv('GITHUB_BRANCH', 'N/A'),
        'GIT_COMMIT': os.getenv('GITHUB_COMMIT', 'N/A'),
        'GIT_COMMIT_SHA': os.getenv('GIT_COMMIT_SHA', 'N/A'),
        'GIT_URL': os.getenv('GIT_URL', 'N/A'),
        'KP_ATLAS_ID': os.getenv('ATLAS_APP_ID', 'N/A'),
        'KP_HOST_IDENTIFIER': os.getenv('DEPLOYMENT_HOST', 'N/A'),
        'KP_TECHNICAL_OWNER_EMAIL_ID': os.getenv('MAIL_ID', 'N/A'),
        'KP_TECHNICAL_OWNER': os.getenv('GITHUB_ACTOR', 'N/A'),
        'BUILD_SYSTEM': 'GHA',
        'BUILD_NUMBER': os.getenv('GITHUB_RUN_NUMBER', 'N/A'),
        'BUILD_ID': os.getenv('GITHUB_RUN_ID', 'N/A'),
        'REPOSITORY': os.getenv('GITHUB_REPOSITORY', 'N/A'),
        'WORKFLOW': os.getenv('GITHUB_WORKFLOW', 'N/A')
    }
    if not all([image_names, vendor_image_registry, project_name]):
        logger.error("Missing required environment variables: IMAGE_NAME, TARGET_REGISTRY, or REGISTRY_FOLDER")
        sys.exit(1)

    try:
        images = [img.strip() for img in image_names.split(',') if img.strip()]
        if not images:
            logger.warning("No valid images found to push.")
            return

        for image in images:
            image_name = '/'.join(image.split('/')[1:])
            logger.info(f"Building image using base: {image}")

            # Write Dockerfile using current base image
            with open("Dockerfile", "w") as dockerfile:
                dockerfile.write(f"FROM {image}\n")

            # Build Docker image
            target_image = f"{vendor_image_registry}/{project_name}/{image_name}"
            logger.info(f"Target image: {target_image}")
            label_args = " ".join([f'--label "{k}={v}"' for k, v in build_args.items()])
            build_cmd = f"docker build -t {image} {label_args} ."
            subprocess.run(build_cmd, shell=True, check=True)

            tag_cmd = f"docker tag {image} {target_image}"
            subprocess.run(tag_cmd, shell=True, check=True)
            logger.info(f"docker image tag: {tag_cmd}")

            push_cmd = f"docker push {target_image}"
            subprocess.run(push_cmd, shell=True, check=True)

            # Remove both original and tagged images
            logger.info(f"Removing image: {target_image}")
            subprocess.run(["docker", "rmi", "--force", image, target_image], check=True)

        logger.info(f"All images pushed to https://docker-baseimages-test-local.devopsrepo.kp.org/ui/repos/tree/General/docker-vendorimages-local/{project_name}")
    except Exception as e:
        logger.error(f"Failed to process Docker images: {e}")
        sys.exit(1)

      
def send_email():
    try:
        # --- Configuration ---
        image_url = os.getenv('IMAGE_URL')
        result = os.getenv('RESULT', 'failure').lower()
        registry = os.getenv('REGISTRY')

# Retrieve the JSON string from the environment variable
        scan_results_file = os.getenv('SCAN_RESULTS_FILE')
        if result == 'success':
            # Parse the JSON string into a Python dictionary
            try:
                data = json.loads(scan_results_file)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON content in SCAN_RESULTS_FILE: {e}")

            # Path to save the JSON file
            output_file_path = 'scan_results.json'

            # Write the dictionary to a JSON file
            with open(output_file_path, 'w') as f:
                json.dump(data, f, indent=2)

        image_name = os.getenv('IMAGE_NAME', 'unknown-image')
        folder_name = os.getenv('FOLDER_NAME')
        git_actor = os.getenv('GITHUB_ACTOR', 'unknown-user')
        image_tag = os.getenv('IMAGE_TAG')
        image_path = os.getenv('IMAGE_PATH')
        
        # Handle multiple recipients (comma-separated)
        recipients = [f"{user.strip()}@kp.org" for user in git_actor.split(",")]
        
        # GitHub context
        github_server = os.getenv('GITHUB_SERVER_URL', 'https://github.com')
        repository = os.getenv('GITHUB_REPOSITORY', 'unknown/repo')  
        github_run_id = os.getenv('GITHUB_RUN_ID')
        build_link = f"{github_server}/{repository}/actions/runs/{github_run_id}"

        # --- Email Content Preparation ---

        if result == 'success':
            console_url = ""
            try:
                if os.path.exists(output_file_path):
                    with open(output_file_path, 'r') as file:
                        scan_data = json.load(file)
                        console_url = scan_data.get("consoleURL", "")
                        logger.info(f"Successfully saved scan results to {output_file_path}")
            except Exception as e:
                logger.error(f"Failed to read scan results: {e}")

            subject = "SUCCESS: Image Published to KP Registry"
            email_message = f"""Dear User,

The following image has been successfully scanned and published:
{image_path}

Details:
- Image: {image_url}:{image_tag}
- Registry: {registry}
- Published By: {git_actor}
- Scan Report: {console_url}
- Build Logs: {build_link}

Best regards,
Your DevOps Team"""
        else:
            subject = "FAILURE: Image Publish to KP Registry"
            email_message = f"""Dear User,

The image publish process failed. Details below:

- Triggered By: {git_actor}
- Failed Build: {build_link}
- Image: {image_url}:{image_tag}

Action Required:
1. Investigate the build logs
2. Retry or contact DevOps

Best regards,
Your DevOps Team"""

        # --- Email Construction ---
        msg = MIMEMultipart()
        msg['Subject'] = subject
        msg['From'] = os.getenv('EMAIL_SENDER', 'githubactions@kp.org')
        msg['To'] = ", ".join(recipients)  # Single To header with all addresses

        # Add body
        msg.attach(MIMEText(email_message, 'plain'))

        # Add attachment for successful scans
        if result == 'success':
            try:
                with open(output_file_path, 'rb') as f:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header(
                        'Content-Disposition',
                        f'attachment; filename="scan_results_{image_name}.json"'
                    )
                    msg.attach(part)
            except Exception as e:
                logger.error(f"Failed to attach scan results: {e}")

        # --- Email Delivery ---
        smtp_server = os.getenv('SMTP_SERVER', 'mta.kp.org')
        smtp_port = int(os.getenv('SMTP_PORT', 25))
        
        logger.info(f"Attempting to send email via {smtp_server}:{smtp_port}")
        
        with smtplib.SMTP(smtp_server, smtp_port, timeout=10) as server:
            # Uncomment if your SMTP requires TLS
            # server.starttls()  
            
            # Verify each recipient before sending
            valid_recipients = []
            for recipient in recipients:
                try:
                    server.verify(recipient)
                    valid_recipients.append(recipient)
                    logger.info(f"Recipient verified: {recipient}")
                except smtplib.SMTPException as e:
                    logger.error(f"Invalid recipient {recipient}: {e}")
            
            if not valid_recipients:
                raise ValueError("No valid recipients found")
            
            server.sendmail(msg['From'], valid_recipients, msg.as_string())
            logger.info(f"Email successfully sent to: {', '.join(valid_recipients)}")

    except Exception as e:
        logger.error(f"Critical email sending failure: {e}")
        raise  # Re-raise to fail the GitHub Action step