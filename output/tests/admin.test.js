const request = require('supertest');
const app = require('../../src/app');

describe('Admin API', () => {
  it('GET /api/admin should return 200', async () => {
    const res = await request(app).get('/api/admin');
    expect(res.statusCode).toBe(200);
  });
});
