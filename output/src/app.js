const express = require('express');
const cors = require('cors');
const helmet = require('helmet');
const { errorHandler } = require('./common/middleware/error-handler');
const { logger } = require('./common/middleware/logger');

const app = express();
app.use(helmet());
app.use(cors());
app.use(express.json());
app.use(logger);
app.use('/api/admin', require('./admin/routes/admin.routes'));
app.use('/api/game', require('./game/routes/game.routes'));
app.use('/api/question', require('./question/routes/question.routes'));
app.use('/api/user', require('./user/routes/user.routes'));

app.get('/health', (req, res) => res.json({ status: 'ok' }));

app.use(errorHandler);

// Initialize database (auto-sync on import)
const { sequelize } = require('./common/config/database');
const dbReady = sequelize.sync({ alter: true }).then(() => {}).catch(() => {});

module.exports = app;
module.exports.dbReady = dbReady;
