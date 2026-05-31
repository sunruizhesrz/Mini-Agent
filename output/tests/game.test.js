const request = require('supertest');
const app = require('../../src/app');

describe('Game API', () => {
  it('GET /api/game should return 200', async () => {
    const res = await request(app).get('/api/game');
    expect(res.statusCode).toBe(200);
  });
});
