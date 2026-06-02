const express = require('express');
const cors = require('cors');
const helmet = require('helmet');
const path = require('path');
const { errorHandler } = require('./common/middleware/error-handler');
const { logger } = require('./common/middleware/logger');

const app = express();
app.use(helmet({
  contentSecurityPolicy: false,  // allow inline scripts for the game page
}));
app.use(cors());
app.use(express.json());
app.use(logger);

// Serve static frontend files
app.use(express.static(path.join(__dirname, 'public')));
app.use('/api/admin', require('./admin/routes/admin.routes'));
app.use('/api/game', require('./game/routes/game.routes'));
app.use('/api/question', require('./question/routes/question.routes'));
app.use('/api/user', require('./user/routes/user.routes'));

app.get('/health', (req, res) => res.json({ status: 'ok' }));

app.get('/', (req, res) => res.sendFile(path.join(__dirname, 'public', 'index.html')));

app.use(errorHandler);

// Initialize database (auto-sync on import)
const { sequelize } = require('./common/config/database');
const dbReady = sequelize.sync({ alter: true }).then(() => {}).catch(() => {});

module.exports = app;
module.exports.dbReady = dbReady;
