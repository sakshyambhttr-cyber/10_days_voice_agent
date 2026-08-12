import { NextResponse } from 'next/server';
import { exec } from 'child_process';
import path from 'path';
import util from 'util';

const execAsync = util.promisify(exec);

export const revalidate = 0;

export async function GET() {
  try {
    const repoRoot = path.resolve(process.cwd(), '..');
    const backendDir = path.join(repoRoot, 'backend');

    const pyScript = `import sys, json; sys.path.append('src'); from db import get_analytics_summary; res = get_analytics_summary(); print(json.dumps(res))`;

    const { stdout } = await execAsync(`uv run python -c "${pyScript}"`, {
      cwd: backendDir,
      timeout: 5000,
    });

    const summary = JSON.parse(stdout.trim() || '{}');

    return NextResponse.json({
      success: true,
      total_calls: summary.total_calls || 0,
      successful_calls: summary.successful_calls || 0,
      failed_calls: summary.failed_calls || 0,
      success_rate: summary.success_rate || 0.0,
      completed_activities: summary.completed_activities || 0,
      failure_reasons: summary.failure_reasons || {},
    });
  } catch (err) {
    console.warn('Analytics summary API GET warning:', err);
    return NextResponse.json(
      {
        success: false,
        total_calls: 0,
        successful_calls: 0,
        failed_calls: 0,
        success_rate: 0.0,
        completed_activities: 0,
        failure_reasons: {},
      },
      { status: 200 }
    );
  }
}
