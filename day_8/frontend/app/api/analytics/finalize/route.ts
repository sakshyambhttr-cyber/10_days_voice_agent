import { NextResponse } from 'next/server';
import { exec } from 'child_process';
import path from 'path';
import util from 'util';

const execAsync = util.promisify(exec);

export const revalidate = 0;

export async function POST(req: Request) {
  try {
    const body = await req.json().catch(() => ({}));
    const targetId = (body?.callId as string) || (body?.userId as string) || '';

    if (!targetId) {
      return NextResponse.json({ success: false, message: 'No targetId provided' });
    }

    const repoRoot = path.resolve(process.cwd(), '..');
    const backendDir = path.join(repoRoot, 'backend');

    const pyScript = `import sys, json; sys.path.append('src'); from db import finalize_call; res = finalize_call('${targetId.replace(/'/g, "\\'")}'); print(json.dumps(res))`;

    const { stdout } = await execAsync(`uv run python -c "${pyScript}"`, {
      cwd: backendDir,
      timeout: 5000,
    });

    const result = JSON.parse(stdout.trim() || '{}');

    return NextResponse.json({
      success: true,
      result,
    });
  } catch (err) {
    console.warn('Analytics finalize API POST warning:', err);
    return NextResponse.json({ success: false, error: String(err) }, { status: 200 });
  }
}
