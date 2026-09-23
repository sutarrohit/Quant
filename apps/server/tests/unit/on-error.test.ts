import { Hono } from 'hono';
import { describe, expect, it } from 'vitest';

import { ApiError } from '../../src/lib/api-error.js';
import onError from '../../src/middlewares/on-error.middleware.js';

function appThatThrows(error: Error) {
  const app = new Hono();
  app.onError(onError);
  app.get('/boom', () => {
    throw error;
  });
  return app;
}

describe('onError', () => {
  it('sends the code an ApiError carries', async () => {
    // ApiErrorSchema always promised a code; the handler never sent one.
    const app = appThatThrows(new ApiError(404, 'JOB_NOT_FOUND', 'no such job'));

    const body = await (await app.request('/boom')).json();

    expect(body).toMatchObject({ statusCode: 404, code: 'JOB_NOT_FOUND', message: 'no such job' });
  });

  it('sends details untouched, so a field-level rejection survives', async () => {
    const errors = [{ path: 'exit', code: 'MISSING_STOP_LOSS', message: 'needs a stop' }];
    const app = appThatThrows(new ApiError(422, 'SPEC_INVALID', 'not runnable', errors));

    const body = await (await app.request('/boom')).json();

    expect(body.details).toEqual(errors);
  });

  it('gives a plain Error a code derived from its status', async () => {
    const app = appThatThrows(new Error('something broke'));

    const response = await app.request('/boom');
    const body = await response.json();

    expect(response.status).toBe(500);
    expect(body.code).toBe('INTERNAL_SERVER_ERROR');
  });

  it('derives a code for every status stoker knows, not just a hand-picked few', async () => {
    // Inverted from stoker, so an unanticipated status still gets a real code.
    const app = appThatThrows(Object.assign(new Error('gone'), { status: 410 }));

    const body = await (await app.request('/boom')).json();

    expect(body.code).toBe('GONE');
  });

  it('omits details entirely when there are none', async () => {
    const app = appThatThrows(new ApiError(409, 'CONFLICT', 'nope'));

    const body = await (await app.request('/boom')).json();

    expect('details' in body).toBe(false);
  });
});
