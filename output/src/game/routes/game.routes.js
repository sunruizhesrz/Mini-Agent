const express = require('express');
const router = express.Router();
const controller = require('../controllers/game.controller');

router.get('/play', controller.play);
router.get('/', controller.getAll);
router.get('/:id', controller.getById);

module.exports = router;
