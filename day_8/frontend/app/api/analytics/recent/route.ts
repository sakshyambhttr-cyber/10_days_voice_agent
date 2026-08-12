import { NextResponse } from 'next/server';
import { exec } from 'child_process';
import path from 'path';
import util from 'util';

const execAsync = util.promisify(exec);

export const revalidate = 0;

export async function GET(req: Request) {
  try {
    const { searchParams } = new URL(req.url);
    const limit = searchParams.get('limit') || '10';

    const repoRoot = path.resolve(process.cwd(), '..');
    const backendDir = path.join(repoRoot, 'backend');

    const pyScript = `import sys, json; sys.path.append('src'); from db import get_recent_calls; res = get_recent_calls(limit=${limit}); print(json.dumps(res))`;

    const { stdout } = await execAsync(`uv run python -c "${pyScript}"`, {
      cwd: backendDir,
      timeout: 5000,
    });

    const recentCalls = JSON.parse(stdout.trim() || '[]');

    return NextResponse.json({
      success: true,
      recent_calls: recentCalls,
    });
  } catch (err) {
    console.warn('Analytics recent API GET warning:', err);
    return NextResponse.json({ success: false, recent_calls: [] }, { status: 200 });
  }
}
