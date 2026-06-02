const request = require('supertest');
const app = require('../src/app');

beforeAll(async () => {
  // Wait for database sync to complete before running tests
  if (app.dbReady) await app.dbReady;
}, 15000);

describe('Question API', () => {
  it('GET /api/question should return 200', async () => {
    const res = await request(app).get('/api/question');
    expect(res.statusCode).toBe(200);
  });
});
