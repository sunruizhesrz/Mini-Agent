const request = require('supertest');
const app = require('../../src/app');

describe('User API', () => {
  it('GET /api/user should return 200', async () => {
    const res = await request(app).get('/api/user');
    expect(res.statusCode).toBe(200);
  });
});
