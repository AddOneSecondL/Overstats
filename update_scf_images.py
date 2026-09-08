"""Update SCF $LATEST images sequentially; default is read-only preview."""
import argparse
import getpass
import json
import os
from pathlib import Path
import time
from datetime import datetime

from tencentcloud.common import credential
from tencentcloud.scf.v20180416 import models, scf_client


def get_function(client, name, namespace):
    req = models.GetFunctionRequest()
    req.from_json_string(json.dumps(dict(FunctionName=name, Namespace=namespace,
                                         Qualifier='$LATEST', ShowCode='FALSE')))
    return client.GetFunction(req)


def update_request(name, namespace, image_config, image):
    config = {k: v for k, v in image_config.items() if v is not None}
    config['ImageUri'] = image
    req = models.UpdateFunctionCodeRequest()
    req.from_json_string(json.dumps(dict(FunctionName=name, Namespace=namespace,
        Publish='FALSE', Code=dict(ImageConfig=config))))
    return req


def image_matches(actual, target):
    return actual == target or ('@' not in target and actual.split('@')[0] == target)


def memory_request(name, namespace, memory):
    req = models.UpdateFunctionConfigurationRequest()
    req.from_json_string(json.dumps(dict(FunctionName=name, Namespace=namespace, MemorySize=memory)))
    return req


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--image')
    mode.add_argument('--memory', type=int, help='Only update memory in MB; leave image unchanged')
    parser.add_argument('--region', required=True)
    parser.add_argument('--namespace', default='default')
    parser.add_argument('--names', nargs='+', required=True)
    parser.add_argument('--apply', action='store_true', help='Actually update; otherwise preview only')
    parser.add_argument('--timeout', type=int, default=900)
    args = parser.parse_args()
    if args.memory is not None and (args.memory < 128 or args.memory % 128):
        parser.error('--memory must be a positive multiple of 128 MB')
    if args.memory is None and args.image is None:
        parser.error('specify --image with an immutable tag, or --memory')
    sid = os.environ.get('TENCENTCLOUD_SECRET_ID') or getpass.getpass('Tencent Cloud SecretId (hidden): ')
    key = os.environ.get('TENCENTCLOUD_SECRET_KEY') or getpass.getpass('Tencent Cloud SecretKey (hidden): ')
    token = os.environ.get('TENCENTCLOUD_SESSION_TOKEN')
    client = scf_client.ScfClient(credential.Credential(sid, key, token), args.region)
    plan = []
    for name in dict.fromkeys(args.names):
        current = get_function(client, name, args.namespace)
        if current.Status != 'Active' or current.ImageConfig is None:
            raise RuntimeError(f'{name}: not an Active image function; no updates started')
        config = json.loads(current.ImageConfig.to_json_string())
        if args.memory is not None:
            print(f'{name}: memory {current.MemorySize} MB -> {args.memory} MB')
        else:
            print(f'{name}: {config.get("ImageUri")} -> {args.image}')
        plan.append(dict(name=name, old_image_config=config, old_memory=current.MemorySize))
    if not args.apply:
        print('Preview only. Run with --apply to perform this update.')
        return
    report = dict(region=args.region, namespace=args.namespace, target=args.image, memory=args.memory, functions=plan)
    path = Path(__file__).with_name('scf-update-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json')
    def save():
        path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    save()
    print(f'Image backup and progress: {path}')
    for item in plan:
        name = item['name']
        if (item['old_memory'] == args.memory if args.memory is not None else image_matches(item['old_image_config']['ImageUri'], args.image)):
            item['result'] = 'already_current'
            save()
            continue
        item['result'] = 'submitting'
        save()
        try:
            if args.memory is not None:
                response = client.UpdateFunctionConfiguration(memory_request(name, args.namespace, args.memory))
            else:
                response = client.UpdateFunctionCode(update_request(name, args.namespace, item['old_image_config'], args.image))
            item['request_id'] = response.RequestId
            item['result'] = 'deploying'
            save()
            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline:
                time.sleep(5)
                current = get_function(client, name, args.namespace)
                status = current.Status or ''
                if 'fail' in status.lower():
                    raise RuntimeError(f'{name}: deployment status {status}; inspect SCF console')
                verified = (current.MemorySize == args.memory if args.memory is not None else current.ImageConfig and image_matches(current.ImageConfig.ImageUri, args.image))
                if status == 'Active' and verified:
                    item['result'] = 'active'
                    print(f'{name}: Active, requested setting verified')
                    break
            else:
                raise TimeoutError(f'{name}: verification timed out; inspect before retrying')
            save()
        except Exception:
            item['result'] = 'failed_or_unknown_check_console'
            save()
            raise
    print('Done. Deployment verified; run an actual image query separately.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Avoid serializing API responses, configuration or credentials.
        code = exc.get_code() if hasattr(exc, 'get_code') else type(exc).__name__
        print(f'Stopped ({code}). Check progress file and SCF console. Credentials were not saved.')
        raise SystemExit(1)
