const { ApiError } = require('../utils/api-error');
const errorHandler = (err, req, res, _next) => {
  const status = err.statusCode || 500;
  res.status(status).json({ error: { message: err.message, status } });
};
module.exports = { errorHandler };
