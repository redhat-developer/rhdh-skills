import { execFile as execFileCb } from 'child_process';
import { promisify } from 'util';

const execFile = promisify(execFileCb);

function parseOwnerRepo(raw) {
  const candidate = String(raw || '').trim();
  const [owner, repo, ...rest] = candidate.split('/');
  if (!owner || !repo || rest.length) {
    return null;
  }
  return `${owner}/${repo}`;
}

function parseGithubRemoteUrl(remoteUrl) {
  if (!remoteUrl) {
    return null;
  }
  const url = remoteUrl.trim();
  const patterns = [
    /^git@github\.com:([^/]+)\/([^/]+?)(?:\.git)?$/,
    /^https?:\/\/github\.com\/([^/]+)\/([^/]+?)(?:\.git)?$/,
    /^ssh:\/\/git@github\.com\/([^/]+)\/([^/]+?)(?:\.git)?$/,
  ];
  for (const pattern of patterns) {
    const match = url.match(pattern);
    if (match) {
      return `${match[1]}/${match[2]}`;
    }
  }
  return null;
}

async function detectRepoFromGit(cwd) {
  try {
    const { stdout } = await execFile(
      'git',
      ['config', '--get', 'remote.origin.url'],
      { cwd },
    );
    return parseGithubRemoteUrl(stdout);
  } catch {
    return null;
  }
}

export async function resolveGithubRepo({
  explicitRepo,
  cwd = process.cwd(),
  requiredFor = 'GitHub API operations',
} = {}) {
  const explicit = parseOwnerRepo(explicitRepo);
  if (explicit) {
    return explicit;
  }

  const envRepo = parseOwnerRepo(process.env.GITHUB_REPOSITORY);
  if (envRepo) {
    return envRepo;
  }

  const gitRepo = await detectRepoFromGit(cwd);
  if (gitRepo) {
    return gitRepo;
  }

  throw new Error(
    `GitHub repository required for ${requiredFor}. Pass --repo owner/name, set GITHUB_REPOSITORY, or run from a checkout with a GitHub origin remote.`,
  );
}
