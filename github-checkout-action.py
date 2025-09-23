import os
import requests
import base64
import subprocess
from kpghalogger import KpghaLogger
logger = KpghaLogger()

COLOR_RED = "\u001b[31m"
workspace = os.getenv('GITHUB_WORKSPACE')

def main():
    """
    Main function to checkout a GitHub repository based on environment variables.

    Environment Variables:
    - CHECKOUT_REPOSITORY: The repository to checkout.
    - CHECKOUT_REF: The reference (branch, tag, commit) to checkout.
    - CHECKOUT_PATH: The path where the repository should be checked out. Defaults to workspace if not provided.
    - CHECKOUT_TOKEN: Explicit token for authentication. Takes precedence over APP_TOKEN and GITHUB_TOKEN.
    - APP_TOKEN: Implicit token for authentication. Used if CHECKOUT_TOKEN is not provided.
    - GITHUB_TOKEN: Default token for authentication. Used if neither CHECKOUT_TOKEN nor APP_TOKEN are provided.
    - CHECKOUT_SPARSE: If provided, specifies a sparse checkout configuration. Should be a newline-separated list of paths.

    Raises:
    - ValueError: If no token is provided for authentication.
    """
    repository = os.getenv('CHECKOUT_REPOSITORY')
    ref = os.getenv('CHECKOUT_REF') or os.getenv('GITHUB_HEAD_REF') or os.getenv('GITHUB_REF')
    path = os.getenv('CHECKOUT_PATH', '') or workspace
    token = os.getenv('CHECKOUT_TOKEN') or os.getenv('APP_TOKEN') or os.getenv('GITHUB_TOKEN')
    if token is None:
        raise ValueError('No token provided. Please provide a token to checkout the repository.')
    sparse_checkout = os.getenv('CHECKOUT_SPARSE')
    if sparse_checkout:
        sparse_checkout = [ x.strip() for x in sparse_checkout.split('\n') if x != '' ]
        sparse_checkout_repo(repository, ref, path, sparse_checkout, token)
    else:
        checkout_repo(repository, ref, path, token)


def sparse_checkout_repo(repository, ref, path, sparse_checkout, token):
    """
    Perform a sparse checkout of specific files from a GitHub repository.

    Args:
        repository (str): The name of the repository (e.g., 'owner/repo').
        ref (str): The branch, tag, or commit SHA to checkout.
        path (str): The local path where the files should be checked out.
        sparse_checkout (list): A list of file paths to checkout from the repository.
        token (str): The GitHub token for authentication.

    Raises:
        Exception: If there is an error fetching any of the specified files.

    Logs:
        Info: When a file is successfully checked out.
        Error: If there is an error fetching a file, including the request URL and response text.
    """
    for i in sparse_checkout:
        workspace_path = '/'.join(i.split('/')[0:-1])
        os.makedirs(f'{path}/{workspace_path}', exist_ok=True)
        logger.info(f'Checking out {i} from {repository}@{ref}.')
        req_url = f"https://github.kp.org/api/v3/repos/{repository}/contents/{i}?ref={ref}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}" 
        }
        payload = ""
        response = requests.request("GET", req_url, data=payload,  headers=headers)
        if response.status_code == 200:
            name = response.json().get('name')
            content = response.json().get('content')
            decoded_content = base64.b64decode(content).decode('utf-8')
            with open(f'{path}/{workspace_path}/{name}', 'w+') as f:
                f.write(decoded_content)
        else:
            logger.error(f'Error fetching file {i} from {repository} at {ref}')
            logger.error(req_url)
            logger.error(response.text)
            raise Exception(f'Error fetching file {i} from {repository} at {ref}')


def checkout_repo(repository, ref, path, token):
    """
    Checks out a GitHub repository at a specific reference (branch, tag, or commit) to a local path.

    Args:
        repository (str): The name of the repository in the format 'owner/repo'.
        ref (str): The reference to check out (branch, tag, or commit SHA).
        path (str): The local file system path where the repository should be checked out.
        token (str): The GitHub token used for authentication.

    Raises:
        RuntimeError: If there is an error fetching the repository or extracting the tarball.

    Example:
        checkout_repo('octocat/Hello-World', 'main', '/path/to/checkout', 'your_github_token')
    """
    os.makedirs(f'{path}', exist_ok=True)
    logger.info(f'Checking out {repository}@{ref}.')
    req_url = f"https://github.kp.org/api/v3/repos/{repository}/tarball/{ref}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}" 
    }
    try:
        with requests.Session() as s:
            r = s.get(req_url, headers=headers)
            r.raise_for_status()
            with open(f'{path}/repo.tar.gz', 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        subprocess.run(['tar', '-xzf', f'{path}/repo.tar.gz', '-C', f'{path}', '--strip-components=1'])
        subprocess.run(['rm', '-f', f'{path}/repo.tar.gz'])
    except (requests.HTTPError, subprocess.CalledProcessError, RuntimeError) as e:
        logger.error(f'Error fetching repository {repository} at {ref}')
        logger.error(req_url)
        logger.error('%s%s', COLOR_RED, e)
        raise RuntimeError(f'Error fetching repository {repository} at {ref}')


if __name__ == '__main__':
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "start"}}))
    main()
    logger.info(logger.format_msg('GHA_EVENT_ACTION_AUD_2_9000', 'action entry/exit point', {"detailMessage": "action metric", "metrics": {"state": "end"}}))