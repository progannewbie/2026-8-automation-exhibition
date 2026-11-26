// SmartCook V2：RViz 視角，和預設 Orbit 一樣，只改滑鼠：
//
//   左鍵拖曳   旋轉
//   右鍵拖曳   平移（原本是縮放）
//   中鍵拖曳   平移
//   滾輪       拉近 / 拉遠
//
// 滾輪：直接在 3D 畫面的 RenderWindow（RenderPanel 裡面的 QWindow，
// 滑鼠事件實際送到這裡）攔 Qt 的滾輪事件自己縮放。
// RViz 內建只讀 angleDelta().y()，有些滑鼠 / 觸控板在 WSLg 下只給 pixelDelta
// 或 x 方向，內建處理會收到 0 而沒反應。

#include <cstdio>

#include <QEvent>
#include <QObject>
#include <QPointer>
#include <QWheelEvent>

#include <rviz_common/display_context.hpp>
#include <rviz_common/properties/float_property.hpp>
#include <rviz_common/render_panel.hpp>
#include <rviz_common/view_manager.hpp>
#include <rviz_common/viewport_mouse_event.hpp>
#include <rviz_default_plugins/view_controllers/orbit/orbit_view_controller.hpp>
#include <rviz_rendering/render_window.hpp>

namespace smartcook_rviz_plugins
{

class RightPanOrbitViewController;

// 掛在 RenderPanel 上的事件過濾器，把滾輪事件轉給視角縮放
class WheelFilter : public QObject
{
public:
  explicit WheelFilter(RightPanOrbitViewController * owner)
  : owner_(owner) {}
  bool eventFilter(QObject * obj, QEvent * e) override;

private:
  RightPanOrbitViewController * owner_;
  int logged_ = 0;
  int logged_press_ = 0;
};

class RightPanOrbitViewController : public rviz_default_plugins::view_controllers::OrbitViewController
{
public:
  ~RightPanOrbitViewController() override
  {
    if (window_) {
      window_->removeEventFilter(&filter_);
    }
  }

  void onActivate() override
  {
    OrbitViewController::onActivate();
    installWheelFilter();
  }

  void handleMouseEvent(rviz_common::ViewportMouseEvent & evt) override
  {
    installWheelFilter();   // RenderPanel 可能在 onActivate 時還沒準備好
    // 右鍵當成中鍵（平移）交給原本的 Orbit 處理
    if (evt.buttons_down & Qt::RightButton) {
      evt.buttons_down = (evt.buttons_down & ~Qt::MouseButtons(Qt::RightButton)) | Qt::MiddleButton;
    }
    if (evt.acting_button == Qt::RightButton) {
      evt.acting_button = Qt::MiddleButton;
    }
    // 滾輪由 WheelFilter 處理，這裡不再縮放一次
    if (evt.type == QEvent::Wheel) {
      return;
    }
    OrbitViewController::handleMouseEvent(evt);
  }

  // 每一格（120）縮放約 12% 的距離，和 RViz 內建相同
  void wheelZoom(int delta)
  {
    float distance = distance_property_->getFloat();
    zoom(static_cast<float>(delta) * 0.001f * distance);
    context_->queueRender();
  }

private:
  void installWheelFilter()
  {
    if (window_ || !context_ || !context_->getViewManager()) {
      return;
    }
    rviz_common::RenderPanel * panel = context_->getViewManager()->getRenderPanel();
    if (!panel || !panel->getRenderWindow()) {
      return;
    }
    window_ = panel->getRenderWindow();
    window_->installEventFilter(&filter_);
    std::fprintf(stderr, "[smartcook_rviz_plugins] 滾輪縮放已啟用（RenderWindow）\n");
  }

  WheelFilter filter_{this};
  QPointer<rviz_rendering::RenderWindow> window_;
};

bool WheelFilter::eventFilter(QObject * obj, QEvent * e)
{
  if (e->type() == QEvent::MouseButtonPress && logged_press_ < 2) {   // 確認滑鼠事件有送到這個視窗
    std::fprintf(stderr, "[smartcook_rviz_plugins] mouse press button=%d\n",
      static_cast<int>(static_cast<QMouseEvent *>(e)->button()));
    ++logged_press_;
  }
  if (e->type() != QEvent::Wheel) {
    return QObject::eventFilter(obj, e);
  }
  auto * w = static_cast<QWheelEvent *>(e);
  const QPoint a = w->angleDelta();
  const QPoint p = w->pixelDelta();
  int delta = a.y() != 0 ? a.y() : a.x();
  if (delta == 0) {
    delta = (p.y() != 0 ? p.y() : p.x()) * 4;   // 像素捲動換算成大約的格數
  }
  if (logged_ < 5) {   // 前幾次印出來，方便確認滑鼠送了什麼
    std::fprintf(stderr, "[smartcook_rviz_plugins] wheel angleDelta=(%d,%d) pixelDelta=(%d,%d) -> %d\n",
      a.x(), a.y(), p.x(), p.y(), delta);
    ++logged_;
  }
  if (delta != 0) {
    owner_->wheelZoom(delta);
  }
  return true;
}

}  // namespace smartcook_rviz_plugins

#include <pluginlib/class_list_macros.hpp>
PLUGINLIB_EXPORT_CLASS(smartcook_rviz_plugins::RightPanOrbitViewController, rviz_common::ViewController)
