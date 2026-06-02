const request = require('supertest');
const app = require('../src/app');

beforeAll(async () => {
  // Wait for database sync to complete before running tests
  if (app.dbReady) await app.dbReady;
}, 15000);

describe('Admin API', () => {
  it('GET /api/admin should return 200', async () => {
    const res = await request(app).get('/api/admin');
    expect(res.statusCode).toBe(200);
  });
});
