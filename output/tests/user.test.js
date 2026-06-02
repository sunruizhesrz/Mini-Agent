const request = require('supertest');
const app = require('../src/app');

beforeAll(async () => {
  // Wait for database sync to complete before running tests
  if (app.dbReady) await app.dbReady;
}, 15000);

describe('User API', () => {
  it('GET /api/user should return 200', async () => {
    const res = await request(app).get('/api/user');
    expect(res.statusCode).toBe(200);
  });
});
