from app import app, db, oid, lm, babel
from flask import render_template, flash, redirect, session, url_for, request, g
from flask_login import login_user, logout_user, current_user, login_required
from .models import User, ROLE_USER, ROLE_ADMIN, Post
from .forms import LoginForm, EditForm, PostForm, SearchForm, EmailLoginForm
from datetime import datetime
from config import POSTS_PER_PAGE, MAX_SEARCH_RESULTS, DATABASE_QUERY_TIMEOUT
from .emails import follower_notification
from config import LANGUAGES
from flask_babel import gettext
from flask_sqlalchemy import get_debug_queries


@app.route('/', methods=['GET', 'POST'])
@app.route('/index', methods=['GET', 'POST'])
@app.route('/index/<int:page>', methods=['GET', 'POST'])
@login_required
def index(page=1):
    form = PostForm()
    if form.validate_on_submit():
        post = Post(body=form.post.data, timestamp=datetime.utcnow(), author=g.user)
        db.session.add(post)
        db.session.commit()
        flash(gettext('Your post is now live!'))
        return redirect(url_for('index'))
    posts = Post.query.order_by(Post.timestamp.desc()).paginate(page, POSTS_PER_PAGE, False) or None
    return render_template('index.html',
                           title='Home',
                           user=user,
                           posts=posts,
                           form=form)


@app.route('/login', methods=['GET', 'POST'])
@oid.loginhandler
def login():
    if g.user is not None and g.user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    form2 = EmailLoginForm()

    if form.validate_on_submit():
        session['remember_me'] = form.remember_me.data
        return oid.try_login(form.openid.data, ask_for=['nickname', 'email'])

    if form2.validate_on_submit():
        session['remember_me'] = form2.remember_me.data
        user = User.query.filter_by(email=form2.email.data).first()
        if user is None:
            # тут можно тоже добавить валидацию, но фтопку
            user = User(
                nickname=form2.email.data.split('@')[0],
                email=form2.email.data,
                role=ROLE_USER
            )
            db.session.add(user)
            db.session.commit()
        remember_me = False
        if 'remember_me' in session:
            remember_me = session['remember_me']
            session.pop('remember_me', None)
        login_user(user, remember=remember_me)
        return redirect(request.args.get('next') or url_for('index'))

    return render_template('login.html',
                           title='Sign in',
                           form=form,
                           form2=form2,
                           providers=app.config['OPENID_PROVIDERS'])


@oid.after_login
def after_login(resp):
    if resp.email is None or resp.email == '':
        flash(gettext('Invalid login. Please try again.'))
        return redirect(url_for('login'))
    user = User.query.filter_by(email=resp.email).first()
    if user is None:
        nickname = resp.nickname
        nickname = User.make_valid_nickname(nickname)
        nickname = User.make_unique_nickname(nickname)
        user = User(nickname=nickname, email=resp.email, role=ROLE_USER)
        if nickname is None or nickname == '':
            nickname = resp.email.split('@')[0]
        user = User(nickname=nickname, email=resp.email, role=ROLE_USER)
        db.session.add(user)
        db.session.commit()
        # выставляем себя фоловерами себя
        db.session.add(user.follow(user))
        db.session.commit()
    remember_me = False
    if 'remember_me' in session:
        remember_me = session['remember_me']
        session.pop('remember_me', None)
    login_user(user, remember=remember_me)
    return redirect(request.args.get('next') or url_for('index'))


@app.before_request
def before_request():
    g.user = current_user
    if g.user.is_authenticated:
        g.user.last_seen = datetime.utcnow()
        db.session.add(g.user)
        db.session.commit()
        g.search_form = SearchForm()


@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/user/<nickname>')
@app.route('/user/<nickname>/<int:page>', methods=['GET', 'POST'])
@login_required
def user(nickname, page=1):
    user = User.query.filter_by(nickname=nickname).first()
    if user is None:
        flash(f'User {nickname} not found')
        return redirect(url_for('index'))
    posts = Post.query.paginate(page, POSTS_PER_PAGE, False) or None
    return render_template('user.html',
                           user=user,
                           posts=posts)


@app.before_request
def before_request():
    g.user = current_user
    if g.user.is_authenticated:
        g.user.last_seen = datetime.utcnow()
        db.session.add(g.user)
        db.session.commit()


@app.after_request
def after_request(response):
    for query in get_debug_queries():
        if query.duration >= DATABASE_QUERY_TIMEOUT:
            app.logger.warning('СЛОУ КВЕРИ: %s\nParameters: %s\nDuration, %fs\nContext: %s\n' %
                               (query.statement, query.parameters, query.duration, query.context))
    return response

@app.route('/edit', methods=['GET', 'POST'])
@login_required
def edit():
    form = EditForm(g.user.nickname)
    if form.validate_on_submit():
        g.user.nickname = form.nickname.data
        g.user.about_me = form.about_me.data
        db.session.add(g.user)
        db.session.commit()
        flash('Your changes have been saved.')
        return redirect(url_for('edit'))
    else:
        form.nickname.data = g.user.nickname
        form.about_me.data = g.user.about_me
    return render_template('edit.html', form=form)


@app.route('/follow/<nickname>')
@login_required
def follow(nickname):
    user = User.query.filter_by(nickname=nickname).first()
    if user is None:
        flash(f'User {nickname} not found.')
        return redirect(url_for('index'))
    if user == g.user:
        flash('You can\'t follow yourself!')
        return redirect(url_for('user', nickname=nickname))
    u = g.user.follow(user)
    if u is None:
        flash(f'Cannot follow {nickname}.')
        return redirect(url_for('user', nickname=nickname))
    db.session.add(u)
    db.session.commit()
    flash(f'You are now following {nickname}!')
    follower_notification(user, g.user)
    return redirect(url_for('user', nickname=nickname))


@app.route('/unfollow/<nickname>')
@login_required
def unfollow(nickname):
    user = User.query.filter_by(nickname=nickname).first()
    args = ('user', nickname)
    if user is None:
        flash(f'User {nickname} not found.')
        return redirect(url_for('index'))
    if user == g.user:
        flash('You can\'t unfollow yourself!')
        return redirect(url_for(args))
    u = g.user.follow(user)
    if u is None:
        flash(f'Cannot unfollow {nickname}.')
        return redirect(args)
    db.session.add(u)
    db.session.commit()
    flash(f'You have stop following {nickname}!')
    return redirect(url_for(args))


@app.route('/delete/<int:id>')
@login_required
def delete(id):
    post = Post.query.get(id)
    if post is None:
        flash('post not found')
        return redirect(url_for('index'))
    if post.author.id != g.user.id:
        flash('you cannot delete this post')
        return redirect(url_for('index'))
    db.session.delete(post)
    db.session.commit()
    flash('post has been deleted')
    return redirect(url_for('index'))


@app.route('/search', methods=['POST'])
@login_required
def search():
    if not g.search_form.validate_on_submit():
        return redirect(url_for('index'))
    return redirect(url_for('search_results', query=g.search_form.search.data))


@app.route('/search_results/<query>')
@login_required
def search_results(query):
    results = Post.query.whoosh_search(query, MAX_SEARCH_RESULTS).all()
    return render_template('search_results.html', query=query, results=results)


@babel.localeselector
def get_locale():
    return "ru" #request.accept_languages.best_match(LANGUAGES.keys())


@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html'), 500