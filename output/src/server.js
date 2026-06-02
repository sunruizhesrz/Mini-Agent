require('dotenv').config();
const app = require('./app');
const PORT = process.env.PORT || 3000;

// Wait for database sync (handled by app.js), then start listening
(app.dbReady || Promise.resolve()).then(() => {
  app.listen(PORT, () => console.log('Space Fractions server running on port ' + PORT));
});
