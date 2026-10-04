import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { PORTFOLIO_PROJECTS } from '../portfolioProjects'

export default function PortfolioPage() {
  const navigate = useNavigate()
  const { logout } = useAuth()
  const enter = (project) => {
    // Each entry starts a fresh visit; navigation inside the project preserves its history.
    for (let i = sessionStorage.length - 1; i >= 0; i -= 1) {
      const key = sessionStorage.key(i)
      if (key?.startsWith('demo-chat:')) sessionStorage.removeItem(key)
    }
    logout()
    navigate(project.route)
  }
  return <div className="portfolio-page">
    <header className="portfolio-header"><a href="/" className="portfolio-brand"><span>✳</span> 个人作品集</a><span className="portfolio-access"><i />已验证访问</span></header>
    <main className="portfolio-main">
      <section className="portfolio-hero">
        <div className="panel-eyebrow">SELECTED WORK / 项目与实践</div>
        <h1>把想法做成<br /><em>可以体验的作品。</em></h1>
        <p>欢迎来到我的作品集。选择一个项目，亲自体验它如何工作。</p>
        <div className="portfolio-count"><b>{String(PORTFOLIO_PROJECTS.length).padStart(2, '0')}</b> 件可体验作品 <span>持续更新中 ↗</span></div>
      </section>
      <section className="portfolio-projects" aria-label="作品列表">
        {PORTFOLIO_PROJECTS.map((project) => <article className="portfolio-project" key={project.id}>
          <div className="project-copy">
            <div className="project-category"><span>{project.number}</span>{project.category}</div>
            <h2>{project.title}</h2><p>{project.description}</p>
            <div className="project-tags">{project.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
            <button className="project-enter" onClick={() => enter(project)}>进入项目体验 <span>↗</span></button>
            <small>选择测试角色，开启一段新的对话。</small>
          </div>
          <div className="project-preview" aria-hidden="true">
            <div className="preview-head"><span className="preview-symbol">✳</span><div>游戏客服助手<small>知识问答 · 账号查询 · 工单跟进</small></div><i /></div>
            <div className="preview-chat user">我上次那个问题解决没有？</div>
            <div className="preview-chat agent"><span>✳</span><div>让每一次提问，都得到有据可查的回应。<div className="preview-tools"><b>查询账号</b><b>检索知识</b><b>跟进工单</b></div></div></div>
            <div className="preview-bottom"><span>玩家体验</span><span>客服工作台</span><span>实时执行记录</span></div>
          </div>
        </article>)}
      </section>
      <footer className="portfolio-footer"><span>更多项目与实习经历作品，将在这里陆续更新。</span><span>感谢你的时间与关注。</span></footer>
    </main>
  </div>
}
