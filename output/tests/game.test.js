const request = require('supertest');
const app = require('../src/app');

beforeAll(async () => {
  // Wait for database sync to complete before running tests
  if (app.dbReady) await app.dbReady;
}, 15000);

describe('Game API', () => {
  it('GET /api/game should return 200', async () => {
    const res = await request(app).get('/api/game');
    expect(res.statusCode).toBe(200);
  });
});
